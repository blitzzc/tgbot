import asyncio
import logging
import secrets
import sqlite3

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

from app.cards import OFFER_STATUS, names, profile_card, team_card, vacancy_card
from app.catalogs import ROLES, normalize_skill
from app.forms import fields
from app.services.core import DomainError

logger = logging.getLogger("team_bot")
MENU = ["Моя анкета", "Команды", "Подходящие команды", "Моя команда / Создать команду", "Заявки и приглашения", "Настройки и помощь"]


class FormState(StatesGroup):
    filling = State()


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
        for row in rows if row
    ])


def menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=label)] for label in MENU], resize_keyboard=True)


async def output(message, text, rows=None, reply_menu=False):
    # Обычный текст: пользовательские символы не интерпретируются как HTML.
    while len(text) > 3500:
        split = text.rfind("\n", 0, 3500)
        split = split if split > 0 else 3500
        await message.answer(text[:split])
        text = text[split:].lstrip("\n")
    markup = menu_keyboard() if reply_menu else (keyboard(rows) if rows else None)
    await message.answer(text, reply_markup=markup)


class BotUI:
    def __init__(self, service):
        self.service = service
        self.config = service.config
        self.router = Router()
        self.router.message.filter(F.chat.type == "private")
        self.router.callback_query.filter(F.message.chat.type == "private")
        self.router.message.register(self.handle_message)
        self.router.callback_query.register(self.handle_callback)

    async def call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.service, method), *args, **kwargs)

    async def main_menu(self, message, state):
        await state.set_state(None)
        await state.update_data(form=None)
        await output(message, f"{self.config.name}\nНайдите команду или соберите свою.\nМаксимум в команде: {self.config.max_team_size}.\nНавыки и опыт участники описывают сами.", reply_menu=True)

    async def handle_message(self, message: Message, state: FSMContext):
        actor = message.from_user.id
        try:
            await self.call("register", actor, message.chat.id)
            text = message.text or ""
            if text == "Найти команду":
                text = "Команды"
            if text.startswith("/start") or text in {"/menu", "/cancel"}:
                await self.main_menu(message, state)
            elif text == "/help":
                await self.help(message)
            elif text in MENU:
                await state.set_state(None)
                await state.update_data(form=None)
                if text == MENU[0]:
                    await self.show_profile(message, actor)
                elif text == MENU[1]:
                    await self.search(message, state, actor, "teams", 0, False, 0)
                elif text == MENU[2]:
                    await self.search(message, state, actor, "teams", 0, True, 0)
                elif text == MENU[3]:
                    await self.my_team(message, actor)
                elif text == MENU[4]:
                    await self.show_offers(message, actor, 0)
                else:
                    await self.help(message)
            elif await state.get_state() == FormState.filling.state:
                await self.form_text(message, state, actor, text)
            else:
                await output(message, "Выберите действие в меню. Для отмены заполнения: /cancel.", reply_menu=True)
        except DomainError as error:
            await output(message, str(error))
        except sqlite3.Error:
            logger.warning("database_error")
            await output(message, "База временно занята или недоступна. Попробуйте ещё раз; состояние можно проверить в меню.")
        except Exception:
            # Не выводим исключение или входящий Update: там могут быть личные данные.
            logger.error("message_processing_error")
            await output(message, "Не удалось выполнить действие. Проверьте результат в меню и попробуйте снова.")

    async def handle_callback(self, query: CallbackQuery, state: FSMContext):
        actor = query.from_user.id
        message = query.message
        if not isinstance(message, Message):
            try:
                await query.answer("Сообщение устарело. Откройте меню командой /menu.", show_alert=True)
            except TelegramBadRequest:
                pass
            return
        try:
            await query.answer()
            await self.call("register", actor, message.chat.id)
            await self.callback(message, state, actor, query.data or "")
        except DomainError as error:
            await output(message, str(error))
        except (ValueError, IndexError, KeyError):
            await output(message, "Кнопка устарела. Откройте нужное действие заново в меню.")
        except sqlite3.Error:
            logger.warning("database_error")
            await output(message, "База временно занята или недоступна. Проверьте состояние в меню и повторите действие.")
        except TelegramBadRequest:
            # Просроченный callback не должен менять сохранённое состояние.
            logger.info("expired_callback")
        except Exception:
            logger.error("callback_processing_error")
            await output(message, "Не удалось выполнить действие. Проверьте результат в меню.")

    async def callback(self, message, state, actor, data):
        bits = data.split(":")
        command = bits[0]
        if command == "f":
            return await self.form_callback(message, state, actor, bits)
        if command == "menu":
            return await self.main_menu(message, state)
        if command == "profile":
            action = bits[1]
            if action == "view":
                return await self.show_profile(message, actor)
            if action == "edit":
                try:
                    initial = await self.call("profile", actor)
                except DomainError:
                    initial = {}
                return await self.start_form(message, state, "profile", initial)
            if action == "visible":
                await self.call("set_visibility", actor, bool(int(bits[2])))
                return await self.show_profile(message, actor)
        if command == "team":
            action = bits[1]
            if action == "create":
                await self.call("profile", actor)
                if await self.call("membership", actor):
                    raise DomainError("Вы уже в команде.")
                return await self.start_form(message, state, "team")
            team_id = int(bits[2])
            if action == "view":
                return await self.show_team(message, actor, team_id)
            if action == "apply":
                can_apply, status = await self.call("team_application_status", actor, team_id)
                if not can_apply:
                    raise DomainError(status + ".")
                return await self.start_form(message, state, "message", context={"kind": "application", "user_id": actor, "place_id": None, "team_id": team_id})
            if action == "edit":
                team = await self.own_team(actor, team_id, True)
                return await self.start_form(message, state, "team", team, {"team_id": team_id})
            if action == "place":
                await self.own_team(actor, team_id, True)
                return await self.start_form(message, state, "vacancy", context={"team_id": team_id})
            if action == "recruit":
                await self.call("set_recruitment", actor, team_id, bool(int(bits[3])))
                return await self.show_team(message, actor, team_id)
            if action in {"leave", "disband"}:
                await self.own_team(actor, team_id, action == "disband")
                label = "расформировать команду и уведомить всех участников" if action == "disband" else "выйти из команды"
                return await output(message, f"Подтвердите: {label}? Старые места автоматически не откроются.", [[("Подтвердить", f"team:{action}_yes:{team_id}")], [("Отмена", f"team:view:{team_id}")]])
            if action == "leave_yes":
                await self.call("leave_team", actor, team_id)
                return await output(message, "Вы вышли из команды.", reply_menu=True)
            if action == "disband_yes":
                await self.call("disband_team", actor, team_id)
                return await output(message, "Команда расформирована. Уведомления сохранены.", reply_menu=True)
            if action == "transfer":
                team = await self.own_team(actor, team_id, True)
                rows = [[(p["name"], f"team:transfer_confirm:{team_id}:{p['user_id']}")] for p in team["members"] if p["user_id"] != actor]
                return await output(message, "Выберите нового капитана из состава." if rows else "Для передачи управления нужен ещё один участник.", rows)
            if action == "transfer_confirm":
                team = await self.own_team(actor, team_id, True)
                new_id = int(bits[3])
                person = next((p for p in team["members"] if p["user_id"] == new_id), None)
                if not person:
                    raise DomainError("Участник уже вышел из команды.")
                return await output(message, "Передать управление участнику: " + person["name"] + "?", [[("Передать", f"team:transfer_yes:{team_id}:{new_id}")], [("Отмена", f"team:view:{team_id}")]])
            if action == "transfer_yes":
                await self.call("transfer_captain", actor, team_id, int(bits[3]))
                return await self.show_team(message, actor, team_id)
            if action == "roles":
                team = await self.own_team(actor, team_id, True)
                return await output(message, "Чью роль в команде изменить?", [[(p["name"], f"team:role:{team_id}:{p['user_id']}")] for p in team["members"]])
            if action == "role":
                await self.own_team(actor, team_id, True)
                return await self.start_form(message, state, "role", context={"team_id": team_id, "user_id": int(bits[3])})
            if action == "contact":
                team = await self.own_team(actor, team_id)
                recipients = ", ".join(p["name"] for p in team["members"] if p["user_id"] != actor)
                if not recipients:
                    raise DomainError("В команде пока нет других участников.")
                await output(message, "Контакт будет отправлен участникам вашей команды: " + recipients + ". Перед отправкой будет предпросмотр. Уже отправленное сообщение отозвать нельзя.")
                return await self.start_form(message, state, "contact", context={"team_id": team_id, "recipients": sorted(p["user_id"] for p in team["members"] if p["user_id"] != actor)})
        if command == "place":
            action, place_id = bits[1], int(bits[2])
            place = await self.call("vacancy", place_id)
            if action == "view":
                return await self.show_place(message, actor, place_id)
            if action == "edit":
                await self.own_team(actor, place["team_id"], True)
                return await self.start_form(message, state, "vacancy", place, {"place_id": place_id, "team_id": place["team_id"]})
            if action == "close":
                await self.own_team(actor, place["team_id"], True)
                return await output(message, "Закрыть место? Активные предложения станут неактуальными.", [[("Закрыть место", f"place:close_yes:{place_id}")], [("Отмена", f"place:view:{place_id}")]])
            if action == "close_yes":
                await self.call("close_vacancy", actor, place_id)
                return await self.show_place(message, actor, place_id)
            if action == "apply":
                await self.call("profile", actor)
                return await self.start_form(message, state, "message", context={"kind": "application", "user_id": actor, "place_id": place_id})
        if command == "search":
            mode, place_id, recommended, page = bits[1], int(bits[2]), bool(int(bits[3])), int(bits[4])
            return await self.search(message, state, actor, mode, place_id, recommended, page)
        if command == "filter":
            mode, place_id, recommended = bits[1], int(bits[2]), bool(int(bits[3]))
            if mode == "people":
                place = await self.call("vacancy", place_id)
                await self.own_team(actor, place["team_id"], True)
            context = {"mode": mode, "place_id": place_id, "recommended": recommended}
            if len(bits) > 4 and bits[4] == "reset":
                await state.update_data(**{self.filter_key(mode, place_id): {}})
                return await self.search(message, state, actor, mode, place_id, recommended, 0)
            return await self.start_form(message, state, "filters", context=context)
        if command == "candidate":
            place_id, user_id = int(bits[1]), int(bits[2])
            profile = await self.call("candidate", actor, place_id, user_id)
            return await output(message, profile_card(profile, self.config.timezone), [[("Пригласить", f"invite:{place_id}:{user_id}")], [("Назад к участникам", f"search:people:{place_id}:0:0")]])
        if command == "invite":
            place_id, user_id = int(bits[1]), int(bits[2])
            await self.call("candidate", actor, place_id, user_id)
            return await self.start_form(message, state, "message", context={"kind": "invitation", "place_id": place_id, "user_id": user_id})
        if command == "offers":
            return await self.show_offers(message, actor, int(bits[1]))
        if command == "offer":
            action, offer_id = bits[1], int(bits[2])
            if action == "view":
                return await self.show_offer(message, actor, offer_id)
            status = await self.call("resolve_offer", actor, offer_id, action)
            await output(message, "Предложение: " + OFFER_STATUS[status] + ".", reply_menu=True)
            return await self.show_offer(message, actor, offer_id)
        if command == "help":
            return await self.help(message)
        raise DomainError("Кнопка устарела. Откройте нужное действие в меню.")

    async def show_profile(self, message, actor):
        try:
            p = await self.call("profile", actor)
        except DomainError:
            return await output(message, "Анкеты пока нет. Проекты и ссылки необязательны; новичок тоже может участвовать.", [[("Заполнить анкету", "profile:edit")]])
        visibility = "Показывается в поиске свободных участников" if p["visible"] else "Скрыта из поиска свободных участников"
        label = "Скрыть из поиска" if p["visible"] else "Показать в поиске"
        await output(message, profile_card(p, self.config.timezone) + "\n\n" + visibility + ".", [[("Изменить анкету", "profile:edit")], [(label, f"profile:visible:{0 if p['visible'] else 1}")]])

    async def own_team(self, actor, team_id, captain=False):
        member = await self.call("membership", actor)
        team = await self.call("team", team_id)
        if not member or member["team_id"] != team_id:
            raise DomainError("Вы не состоите в этой команде.")
        if captain and team["captain_id"] != actor:
            raise DomainError("Это действие доступно только текущему капитану.")
        return team

    async def my_team(self, message, actor):
        member = await self.call("membership", actor)
        if member:
            return await self.show_team(message, actor, member["team_id"])
        await output(message, "Вы пока не в команде. Для создания нужна сохранённая анкета. Создатель станет капитаном и первым участником.", [[("Создать команду", "team:create")], [("Команды", "search:teams:0:0:0")]])

    async def show_team(self, message, actor, team_id):
        team = await self.call("team", team_id)
        member = await self.call("membership", actor)
        own = bool(member and member["team_id"] == team_id)
        captain = own and team["captain_id"] == actor
        can_apply, application_status = await self.call("team_application_status", actor, team_id)
        rows = [[(f"Место №{p['id']}: {ROLES[p['role']]} · {p['status'] == 'open' and 'открыто' or 'закрыто'}", f"place:view:{p['id']}")] for p in team["vacancies"] if captain or p["status"] == "open"]
        if can_apply:
            rows.insert(0, [("Подать заявку в команду", f"team:apply:{team_id}")])
        elif not own and application_status == "Сначала заполните анкету":
            rows.insert(0, [("Заполнить анкету", "profile:edit")])
        elif application_status == "Заявка уже отправлена":
            rows.insert(0, [("Мои заявки", "offers:0")])
        if own:
            rows.append([("Поделиться контактом", f"team:contact:{team_id}")])
            if captain:
                rows.extend([
                    [("Добавить место", f"team:place:{team_id}")],
                    [("Изменить команду", f"team:edit:{team_id}"), ("Роли в составе", f"team:roles:{team_id}")],
                    [("Приостановить набор" if team["status"] == "open" else "Возобновить набор", f"team:recruit:{team_id}:{int(team['status'] != 'open')}")],
                    [("Передать управление", f"team:transfer:{team_id}")],
                    [("Расформировать команду", f"team:disband:{team_id}")],
                ])
            else:
                rows.append([("Выйти из команды", f"team:leave:{team_id}")])
        await output(message, team_card(team, self.config.max_team_size) + "\n\nЗаявки: " + application_status + ".", rows)

    async def show_place(self, message, actor, place_id):
        place = await self.call("vacancy", place_id)
        team = await self.call("team", place["team_id"])
        member = await self.call("membership", actor)
        captain = team["captain_id"] == actor and member and member["team_id"] == team["id"]
        rows = [[("Команда и состав", f"team:view:{team['id']}")]]
        if captain and place["status"] == "open":
            rows.extend([
                [("Поиск участников", f"search:people:{place_id}:0:0")],
                [("Подходящие участники", f"search:people:{place_id}:1:0")],
                [("Заявки и приглашения", "offers:0")],
                [("Изменить место", f"place:edit:{place_id}"), ("Закрыть место", f"place:close:{place_id}")],
            ])
        elif not member and place["status"] == "open" and team["status"] == "open":
            rows.append([("Отправить заявку", f"place:apply:{place_id}")])
        await output(message, f"Команда: {team['name']}\n\n" + vacancy_card(place, self.config.timezone), rows)

    @staticmethod
    def filter_key(mode, place_id):
        return f"filters_{mode}_{place_id}"

    async def search(self, message, state, actor, mode, place_id, recommended, page):
        if mode not in {"teams", "people"}:
            raise DomainError("Неизвестный раздел поиска.")
        data = await state.get_data()
        filters = data.get(self.filter_key(mode, place_id), {})
        if mode == "teams":
            results = await self.call("search_teams", actor, recommended, filters)
        else:
            results = await self.call("search_people", actor, place_id, recommended, filters)
        total_pages = max(1, (len(results) + 4) // 5)
        page = max(0, min(page, total_pages - 1))
        label = "Подходящие команды" if mode == "teams" else "Подходящие участники"
        if not recommended:
            label = "Команды" if mode == "teams" else "Поиск участников"
        text = f"{label}. Страница {page + 1}/{total_pages}. Найдено: {len(results)}."
        if filters:
            text += "\nФильтры: " + "; ".join(self.filter_summary(filters))
        if not results:
            text += "\nНичего не найдено. Попробуйте изменить или сбросить фильтры."
        rows = []
        for number, item in enumerate(results[page * 5:page * 5 + 5], start=page * 5 + 1):
            if mode == "teams":
                t, v = item["team"], item["vacancy"]
                text += f"\n\n{number}. {t['name']} · {item['count']}/{self.config.max_team_size}\nТема: {t['idea'][:160]}\nЗаявки: {item['application_status']}."
                buttons = [(f"{number}. Команда и состав", f"team:view:{t['id']}")]
                if v:
                    text += f"\nПозиция: {ROLES[v['role']]}\nНавыки: {names(v['required'] + v['desired'])[:140]}"
                    buttons.append(("Требования места", f"place:view:{v['id']}"))
                rows.append(buttons)
            else:
                p = item["profile"]
                text += f"\n\n{number}. " + profile_card(p, self.config.timezone, True)
                rows.append([(f"{number}. Подробнее", f"candidate:{place_id}:{p['user_id']}")])
            if recommended:
                text += "\nПочему подходит: " + "; ".join(item["why"]) + "."
        navigation = []
        if page > 0:
            navigation.append(("← Назад", f"search:{mode}:{place_id}:{int(recommended)}:{page - 1}"))
        if page < total_pages - 1:
            navigation.append(("Далее →", f"search:{mode}:{place_id}:{int(recommended)}:{page + 1}"))
        rows.extend([navigation, [("Изменить фильтры", f"filter:{mode}:{place_id}:{int(recommended)}")], [("Сбросить фильтры", f"filter:{mode}:{place_id}:{int(recommended)}:reset")]])
        if mode == "people":
            rows.append([("Назад к месту", f"place:view:{place_id}")])
        await output(message, text, rows)

    @staticmethod
    def filter_summary(values):
        result = []
        for key, catalog in (("role", ROLES),):
            if values.get(key):
                result.append(catalog[values[key]])
        if values.get("skills"):
            result.append("Навыки: " + names(values["skills"]))
        return result or ["Без дополнительных фильтров"]

    async def show_offers(self, message, actor, page):
        items = await self.call("offers", actor)
        pages = max(1, (len(items) + 4) // 5)
        page = max(0, min(page, pages - 1))
        text = f"Заявки и приглашения. Страница {page + 1}/{pages}."
        rows = []
        for offer in items[page * 5:page * 5 + 5]:
            kind = "Заявка" if offer["kind"] == "application" else "Приглашение"
            target = ROLES[offer['vacancy']['role']] if offer["vacancy"] else "Общая заявка в команду"
            text += f"\n\n№{offer['id']} · {kind} · {offer['team']['name']}\n{target} · {OFFER_STATUS[offer['status']]}"
            rows.append([(f"Открыть №{offer['id']}", f"offer:view:{offer['id']}")])
        if not items:
            text += "\nПредложений пока нет. Найдите команду или пригласите участника из управления местом."
        nav = []
        if page:
            nav.append(("← Назад", f"offers:{page - 1}"))
        if page + 1 < pages:
            nav.append(("Далее →", f"offers:{page + 1}"))
        rows.append(nav)
        await output(message, text, rows)

    async def show_offer(self, message, actor, offer_id):
        offer = await self.call("offer", actor, offer_id)
        kind = "Заявка" if offer["kind"] == "application" else "Приглашение"
        text = f"{kind} №{offer_id} · {OFFER_STATUS[offer['status']]}\nКоманда: {offer['team']['name']}\nСообщение: {offer['message']}"
        if offer["reason"]:
            text += "\nПричина: " + offer["reason"]
        text += "\n\n" + (vacancy_card(offer["vacancy"], self.config.timezone) if offer["vacancy"] else "Общая заявка без выбора позиции. При принятии роль берётся из анкеты; капитан может изменить её в составе.")
        text += "\n\n" + profile_card(offer["profile"], self.config.timezone)
        rows = []
        if offer["team"]["status"] != "disbanded":
            rows.append([("Команда и состав", f"team:view:{offer['team']['id']}")])
        if offer["status"] == "pending":
            recipient = offer["team"]["captain_id"] if offer["kind"] == "application" else offer["user_id"]
            if actor == recipient:
                rows.append([("Принять", f"offer:accept:{offer_id}"), ("Отклонить", f"offer:reject:{offer_id}")])
            if actor == offer["sender_id"]:
                rows.append([("Отменить предложение", f"offer:cancel:{offer_id}")])
        rows.append([("Все предложения", "offers:0")])
        await output(message, text, rows)

    async def help(self, message):
        await output(message,
            "Как пользоваться\n"
            "1. Заполните анкету: проекты и ссылки необязательны.\n"
            "2. В разделе «Команды» можно посмотреть состав и статус заявок. Общую заявку можно отправить без выбора позиции. Капитан также может создать отдельные позиции.\n"
            "3. Вступление происходит через принятую заявку или приглашение. До вступления можно иметь несколько предложений.\n\n"
            "Подбор: сначала обязательные навыки и требование опыта; затем основная/дополнительная роль и число желательных навыков. При равенстве — порядок ID. Процентов и общего рейтинга нет.\n"
            "Скрытая анкета не попадает в поиск участников; уже отправленные предложения сохраняются. Состав команды остаётся виден в карточке команды.\n"
            "Роль команды назначает капитан, личную анкету редактируете только вы.\n\n"
            "Приватность: сохраняем Telegram ID и ID чата для работы бота, анкету и действия внутри команды. Username и телефон автоматически не собираем. Контакт отправляется только после вашего подтверждения. Ссылки, которые вы сами добавили в анкету, видны в её подробностях.\n"
            "Навыки и опыт не проверены и указаны самими участниками. Токен и содержимое анкет не записываются в журналы.\n"
            "Отмена формы: /cancel. После перезапуска незавершённую форму нужно заполнить заново; сохранённые данные остаются.\n"
            "Бот — прототип для одного соревнования. Нет автоматической проверки навыков и обещаний успеха команды.",
            [[("Моя анкета и видимость", "profile:view")], [("Главное меню", "menu")]],
        )

    async def start_form(self, message, state, kind, initial=None, context=None):
        await state.set_state(FormState.filling)
        await state.update_data(form={"kind": kind, "step": 0, "values": dict(initial or {}), "context": context or {}, "custom": False, "visible": (initial or {}).get("visible", True)})
        await output(message, "Заполнение: можно вернуться назад, посмотреть результат перед сохранением или отменить. Пока не нажата кнопка сохранения, изменения не применяются.")
        await self.render_form(message, state)

    async def render_form(self, message, state):
        form = (await state.get_data()).get("form")
        if not form:
            raise DomainError("Форма уже закрыта. Откройте действие заново.")
        definition = fields(form["kind"], self.config)
        form["nonce"] = secrets.token_hex(3)
        prefix = "f:" + form["nonce"] + ":"
        rows = []
        if form["step"] >= len(definition):
            form["preview"] = True
            try:
                text = await self.preview(form)
            except DomainError as error:
                form["step"] = 0
                await state.update_data(form=form)
                await output(message, str(error) + " Вернитесь к нужному полю и исправьте; введённые значения сохранены в черновике.")
                return await self.render_form(message, state)
            rows = [[("Сохранить" if form["kind"] not in {"message", "contact"} else "Отправить", prefix + "save")], [("Исправить с начала", prefix + "restart")]]
        else:
            form["preview"] = False
            spec = definition[form["step"]]
            key = spec["key"]
            text = f"Шаг {form['step'] + 1}/{len(definition)}\n{spec['title']}"
            if spec["kind"] == "text":
                text += f"\nОтправьте текст сообщением (до {spec['maximum']} символов)."
            elif spec["kind"] == "skills":
                options = await self.call("skill_names")
                options = list(dict.fromkeys(options + form["values"].get(key, [])))
                form["options"] = [(value, value) for value in options]
            else:
                form["options"] = list(spec["options"].items())
            if spec["kind"] in {"multi", "skills"}:
                values = form["values"].get(key, [])
                selected = {normalize_skill(s) for s in values} if spec["kind"] == "skills" else set(values)
                for index, (value, label) in enumerate(form["options"]):
                    checked = normalize_skill(value) in selected if spec["kind"] == "skills" else value in selected
                    rows.append([(("✓ " if checked else "") + label, prefix + f"pick:{index}")])
                if spec["kind"] == "skills":
                    rows.append([("Добавить свой навык", prefix + "custom")])
                rows.append([("Готово", prefix + "next")])
            elif spec["kind"] == "choice":
                rows += [[(label, prefix + f"pick:{index}")] for index, (_, label) in enumerate(form["options"])]
            old = form["values"].get(key)
            if old and spec["kind"] in {"text", "choice"}:
                label = spec["options"].get(old, old) if spec["options"] else old
                text += "\nТекущее значение: " + str(label)
                rows.append([("Оставить текущее", prefix + "keep")])
            if not spec["required"]:
                rows.append([("Пропустить", prefix + "skip")])
        if form["step"] > 0:
            rows.append([("← Предыдущий шаг", prefix + "back")])
        rows.append([("Отменить заполнение", prefix + "cancel")])
        form["custom"] = False
        await state.update_data(form=form)
        await output(message, text, rows)

    async def preview(self, form):
        kind, values, context = form["kind"], form["values"], form["context"]
        if kind == "profile":
            values = await self.call("validate_profile", values)
            form["values"] = values
            visible = form.get("visible", True)
            return "Предпросмотр\n\n" + profile_card(values, self.config.timezone) + ("\n\nПосле сохранения анкета доступна в поиске, если вы свободны. Контакт не раскрывается автоматически." if visible else "\n\nАнкета останется скрытой из поиска.")
        if kind == "team":
            values = await self.call("validate_team", values)
            form["values"] = values
            return "Предпросмотр\n\n" + team_card(values, self.config.max_team_size, False)
        if kind == "vacancy":
            values = await self.call("validate_vacancy", values)
            form["values"] = values
            return "Предпросмотр\n\n" + vacancy_card(values, self.config.timezone)
        if kind == "filters":
            return "Применить фильтры?\n" + "; ".join(self.filter_summary(values))
        if kind == "message":
            place = await self.call("vacancy", context["place_id"]) if context["place_id"] is not None else None
            team = await self.call("team", place["team_id"] if place else context["team_id"])
            label = "Заявка" if context["kind"] == "application" else "Приглашение"
            target = f"место №{place['id']} ({ROLES[place['role']]})" if place else "без выбора позиции"
            return f"{label} в команду «{team['name']}», {target}.\nСообщение: {values['message']}\nОтправить?"
        if kind == "contact":
            team = await self.call("team", context["team_id"])
            recipients = [p["name"] for p in team["members"] if p["user_id"] in context["recipients"]]
            return "Добровольная передача контакта\nПолучатели: " + ", ".join(recipients) + "\nКонтакт: " + values["contact"] + "\nОтправить этим участникам?"
        return "Новая роль в команде: " + ROLES[values["role"]] + ". Сохранить?"

    async def form_text(self, message, state, actor, text):
        form = (await state.get_data()).get("form")
        if not form:
            raise DomainError("Форма закрыта. Откройте нужное действие в меню.")
        definition = fields(form["kind"], self.config)
        if form["step"] >= len(definition):
            raise DomainError("Используйте кнопки «Сохранить», «Исправить» или «Отменить» под предпросмотром.")
        spec = definition[form["step"]]
        if form["custom"]:
            skills = form["values"].get(spec["key"], [])
            skills = self.service._skills(skills + [text.strip()])
            form["values"][spec["key"]] = skills
        elif spec["kind"] != "text":
            raise DomainError("Выберите вариант кнопками. Для своего навыка сначала нажмите «Добавить свой навык».")
        else:
            text = text.strip()
            if not text or len(text) > spec["maximum"]:
                raise DomainError(f"Отправьте от 1 до {spec['maximum']} символов.")
            form["values"][spec["key"]] = text
            form["step"] += 1
        await state.update_data(form=form)
        await self.render_form(message, state)

    async def form_callback(self, message, state, actor, bits):
        form = (await state.get_data()).get("form")
        if not form or form.get("nonce") != bits[1]:
            raise DomainError("Эта кнопка формы устарела. Используйте кнопки под последним шагом.")
        action = bits[2]
        definition = fields(form["kind"], self.config)
        if action == "cancel":
            await state.set_state(None)
            await state.update_data(form=None)
            return await output(message, "Заполнение отменено. Сохранённые данные не изменены.", reply_menu=True)
        if action == "save":
            if not form.get("preview"):
                raise DomainError("Сначала завершите заполнение и посмотрите предпросмотр.")
            return await self.save_form(message, state, actor, form)
        if action == "restart":
            form["step"] = 0
        elif action == "back":
            form["step"] = max(0, form["step"] - 1)
        else:
            if form["step"] >= len(definition):
                raise DomainError("Используйте кнопки предпросмотра.")
            spec = definition[form["step"]]
            key = spec["key"]
            if action == "custom" and spec["kind"] == "skills":
                form["custom"] = True
                await state.update_data(form=form)
                return await output(message, "Отправьте название одного навыка (до 40 символов). Для отмены ввода нажмите «Готово» под текущим списком.")
            if action == "pick":
                index = int(bits[3])
                if index < 0 or index >= len(form.get("options", [])):
                    raise DomainError("Кнопка устарела.")
                value = form["options"][index][0]
                if spec["kind"] == "choice":
                    form["values"][key] = value
                    form["step"] += 1
                elif spec["kind"] in {"multi", "skills"}:
                    values = list(form["values"].get(key, []))
                    matches = [v for v in values if (normalize_skill(v) == normalize_skill(value) if spec["kind"] == "skills" else v == value)]
                    if matches:
                        values = [v for v in values if v not in matches]
                    else:
                        values.append(value)
                    if spec["kind"] == "skills":
                        values = self.service._skills(values)
                    form["values"][key] = values
                else:
                    raise DomainError("Это поле заполняется текстом.")
            elif action == "skip" and not spec["required"]:
                form["values"][key] = [] if spec["kind"] in {"multi", "skills"} else ""
                form["step"] += 1
            elif action in {"next", "keep"}:
                values = form["values"].get(key)
                if spec["required"] and not values:
                    raise DomainError("Сначала заполните поле или выберите значение.")
                if values is None:
                    form["values"][key] = [] if spec["kind"] in {"multi", "skills"} else ""
                form["step"] += 1
            else:
                raise DomainError("Кнопка устарела.")
        await state.update_data(form=form)
        await self.render_form(message, state)

    async def save_form(self, message, state, actor, form):
        kind, values, context = form["kind"], form["values"], form["context"]
        result = None
        if kind == "profile":
            await self.call("save_profile", actor, values)
        elif kind == "team":
            if "team_id" in context:
                await self.call("update_team", actor, context["team_id"], values)
                result = context["team_id"]
            else:
                result = await self.call("create_team", actor, values)
        elif kind == "vacancy":
            if "place_id" in context:
                await self.call("update_vacancy", actor, context["place_id"], values)
                result = context["place_id"]
            else:
                result = await self.call("create_vacancy", actor, context["team_id"], values)
        elif kind == "message":
            result = await self.call("create_offer", actor, context["kind"], context["user_id"], context["place_id"], values["message"], context.get("team_id"))
        elif kind == "contact":
            team = await self.own_team(actor, context["team_id"])
            current = sorted(p["user_id"] for p in team["members"] if p["user_id"] != actor)
            if current != context["recipients"]:
                raise DomainError("Состав изменился. Начните передачу контакта заново, чтобы подтвердить новых получателей.")
            await self.call("share_contact", actor, context["team_id"], values["contact"], context["recipients"])
        elif kind == "role":
            await self.call("change_role", actor, context["team_id"], context["user_id"], values["role"])
        elif kind == "filters":
            await state.update_data(**{self.filter_key(context["mode"], context["place_id"]): values})
        await state.set_state(None)
        await state.update_data(form=None)
        if kind == "filters":
            return await self.search(message, state, actor, context["mode"], context["place_id"], context["recommended"], 0)
        await output(message, "Отправлено. Уведомления будут доставлены через бота." if kind in {"message", "contact"} else "Сохранено.", reply_menu=True)
        if kind == "profile":
            await self.show_profile(message, actor)
        elif kind == "team":
            await self.show_team(message, actor, result)
        elif kind == "vacancy":
            await self.show_place(message, actor, result)
        elif kind == "message":
            await self.show_offer(message, actor, result)
        elif kind in {"contact", "role"}:
            await self.show_team(message, actor, context["team_id"])


def build_dispatcher(service):
    dispatcher = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dispatcher.include_router(BotUI(service).router)
    return dispatcher


async def deliver_notifications(bot: Bot, service):
    rows = await asyncio.to_thread(service.pending_notifications)
    for row in rows:
        success, permanent, retry_after = False, False, None
        try:
            await bot.send_message(row["chat_id"], row["body"], parse_mode=None)
            success = True
        except TelegramRetryAfter as error:
            retry_after = error.retry_after
        except (TelegramForbiddenError, TelegramBadRequest):
            permanent = True
        except TelegramNetworkError:
            pass
        except Exception:
            logger.warning("notification_delivery_error")
        await asyncio.to_thread(service.notification_result, row["id"], success, permanent, retry_after)
        if retry_after is not None:
            return retry_after


async def notification_loop(bot, service):
    while True:
        delay = 2
        try:
            delay = max(2, (await deliver_notifications(bot, service)) or 2)
        except Exception:
            logger.warning("notification_worker_error")
        await asyncio.sleep(delay)
