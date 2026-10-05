import asyncio

from app.bot import deliver_notifications
from tests.conftest import add_person, place_data, setup_place
from tests.telegram_harness import TelegramHarness, create_team_and_place, fill_profile


async def application_flow(service):
    h = TelegramHarness(service)
    try:
        # Два разных ID, два независимых диалога с ботом, без прямого создания данных.
        await fill_profile(h, 101, "[ТЕСТ] Капитан")
        await create_team_and_place(h, 101)
        team_id = service.membership(101)["team_id"]
        place = service.team(team_id)["vacancies"][0]["id"]
        await fill_profile(h, 202, "[ТЕСТ] Участник")
        await h.send(202, "Найти команду")
        assert "[ТЕСТ] Команда прототипа" in h.last(202).text
        await h.click(202, "1. Команда и состав")
        assert "Состав: 1/4" in h.last(202).text
        assert "[ТЕСТ] Капитан" in h.last(202).text
        await h.callback(202, f"place:view:{place}")
        assert "Обязательные навыки: Python" in h.last(202).text
        await h.send(202, "Подходящие команды")
        assert "Почему подходит" in h.last(202).text
        assert "PostgreSQL" in h.last(202).text
        await h.click(202, "Требования места")
        await h.click(202, "Отправить заявку")
        await h.send(202, "Готов сделать API по выходным")
        await h.click(202, "Отправить")
        offer = service.offers(202)[0]["id"]
        await deliver_notifications(h.bot, service)
        assert "Новое предложение" in h.last(101).text
        await h.send(101, "Заявки и приглашения")
        await h.click(101, f"Открыть №{offer}")
        accept_message = h.last(101)
        await h.click(101, "Принять")
        assert service.offer(202, offer)["status"] == "accepted"
        await h.callback(101, f"offer:accept:{offer}", accept_message)
        await h.send(101, "Моя команда / Создать команду")
        assert "Состав: 2/4" in h.last(101).text
        assert "[ТЕСТ] Участник" in h.last(101).text
        assert service.vacancy(place)["status"] == "filled"
        another_place = service.create_vacancy(101, team_id, place_data())
        await h.callback(101, f"search:people:{another_place}:0:0")
        assert "Найдено: 0" in h.last(101).text
        await deliver_notifications(h.bot, service)
        assert "принято — состав обновлён" in h.text(202)
        return h.session.sent
    finally:
        await h.close()


def test_entire_application_flow_via_telegram_dispatcher(service):
    asyncio.run(application_flow(service))


async def invitation_flow(service):
    h = TelegramHarness(service)
    try:
        await fill_profile(h, 101, "[ТЕСТ] Капитан")
        await create_team_and_place(h, 101)
        await fill_profile(h, 202, "[ТЕСТ] Участник")
        team_id = service.membership(101)["team_id"]
        place = service.team(team_id)["vacancies"][0]["id"]
        await h.send(101, "Моя команда / Создать команду")
        await h.callback(101, f"place:view:{place}")
        await h.click(101, "Подходящие участники")
        assert "Почему подходит" in h.last(101).text
        await h.click(101, "1. Подробнее")
        await h.click(101, "Пригласить")
        await h.send(101, "Приглашаю сделать API вместе")
        await h.click(101, "Отправить")
        offer = service.offers(202)[0]["id"]
        assert service.membership(202) is None
        await deliver_notifications(h.bot, service)
        await h.send(202, "Заявки и приглашения")
        await h.click(202, f"Открыть №{offer}")
        await h.click(202, "Команда и состав")
        assert "Состав: 1/4" in h.last(202).text
        await h.callback(202, f"offer:view:{offer}")
        await h.click(202, "Принять")
        assert service.membership(202)["team_id"] == team_id
        await h.send(202, "Моя команда / Создать команду")
        assert "Состав: 2/4" in h.last(202).text
        await h.click(202, "Поделиться контактом")
        await h.send(202, "@test_participant")
        assert "[ТЕСТ] Капитан" in h.last(202).text
        assert service.membership(202)["shared_contact"] is None
        await h.click(202, "Отправить")
        await deliver_notifications(h.bot, service)
        assert "@test_participant" in h.text(101)
        await h.send(202, "Моя команда / Создать команду")
        await h.click(202, "Выйти из команды")
        await h.click(202, "Подтвердить")
        assert service.membership(202) is None
        assert service.vacancy(place)["status"] == "filled"
        return h.session.sent
    finally:
        await h.close()


def test_entire_invitation_flow_via_telegram_dispatcher(service):
    asyncio.run(invitation_flow(service))


def test_cancel_edit_custom_skills_and_expired_form_buttons(service):
    async def scenario():
        h = TelegramHarness(service)
        try:
            await fill_profile(h, 202, "Сохранённое имя")
            original = service.profile(202)
            await h.click(202, "Изменить анкету")
            old_message = h.last(202)
            old_button = old_message.reply_markup.inline_keyboard[0][0].callback_data
            await h.send(202, "Новое имя")
            await h.callback(202, old_button, old_message)
            assert "устарела" in h.last(202).text
            await h.send(202, "/cancel")
            assert service.profile(202) == original
            await h.send(202, "Моя анкета")
            await h.click(202, "Скрыть из поиска")
            assert not service.profile(202)["visible"]
            await h.click(202, "Показать в поиске")
            assert service.profile(202)["visible"]
            await h.click(202, "Изменить анкету")
            await h.click(202, "Оставить текущее")
            await h.click(202, "Оставить текущее")
            await h.click(202, "Пропустить")
            await h.click(202, "Добавить свой навык")
            await h.send(202, "Мой   Навык")
            assert "Мой   Навык" in [b.text.removeprefix("✓ ") for row in h.last(202).reply_markup.inline_keyboard for b in row]
            await h.click(202, "Отменить заполнение")
            assert service.profile(202) == original
        finally:
            await h.close()
    asyncio.run(scenario())


def test_pagination_filter_reset_and_forged_callback_permissions(service):
    async def scenario():
        team_id, place = setup_place(service)
        for actor in range(202, 209):
            add_person(service, actor)
        h = TelegramHarness(service)
        try:
            await h.send(101, "/start")
            await h.callback(101, f"search:people:{place}:0:0")
            assert "Страница 1/2" in h.last(101).text
            await h.click(101, "Далее →")
            assert "Страница 2/2" in h.last(101).text
            await h.click(101, "Изменить фильтры")
            await h.click(101, "Дизайнер")
            for _ in range(1):
                await h.click(101, "Пропустить")
            await h.click(101, "Сохранить")
            assert "Найдено: 0" in h.last(101).text
            await h.click(101, "Сбросить фильтры")
            assert "Найдено: 7" in h.last(101).text
            await h.send(202, "/start")
            await h.callback(202, f"place:close_yes:{place}")
            assert "капитану" in h.last(202).text
            assert service.vacancy(place)["status"] == "open"
        finally:
            await h.close()
    asyncio.run(scenario())


def test_bad_links_can_be_corrected_before_save(service):
    async def scenario():
        h = TelegramHarness(service)
        try:
            await fill_profile(h, 202, "Исходная анкета")
            await h.click(202, "Изменить анкету")
            for _ in range(2):
                await h.click(202, "Оставить текущее")
            await h.click(202, "Пропустить")
            await h.click(202, "Готово")
            for _ in range(2):
                await h.click(202, "Оставить текущее")
            await h.click(202, "Пропустить")
            await h.send(202, "javascript:bad")
            assert "Шаг 1/8" in h.last(202).text
            assert service.profile(202)["links"] == ""
            await h.click(202, "Отменить заполнение")
        finally:
            await h.close()
    asyncio.run(scenario())


def test_inaccessible_old_message_does_not_execute_action(service):
    async def scenario():
        from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Update, User
        team_id, place = setup_place(service)
        h = TelegramHarness(service)
        try:
            query = CallbackQuery(
                id="old-message", from_user=User(id=101, is_bot=False, first_name="Капитан"),
                chat_instance="101", data=f"place:close_yes:{place}",
                message=InaccessibleMessage(chat=Chat(id=101, type="private"), message_id=1, date=0),
            )
            await h.dispatcher.feed_update(h.bot, Update(update_id=1, callback_query=query))
            assert h.session.answers[0].show_alert
            assert "устарело" in h.session.answers[0].text
            assert service.vacancy(place)["status"] == "open"
        finally:
            await h.close()
    asyncio.run(scenario())
