import asyncio
import time
import pytest

from aiogram.fsm.storage.base import StorageKey
from app.services.core import Service
from app.storage import SQLiteStorage
from tests.telegram_harness import TelegramHarness
from tests.conftest import add_person, setup_place


@pytest.mark.parametrize("kind", ["team", "vacancy", "filters"])
def test_real_dialog_and_filters_continue_after_restart(service, kind):
    async def scenario():
        add_person(service, 101)
        if kind != "team":
            team, _ = setup_place(service, captain=303)
        h = TelegramHarness(service)
        actor = 303 if kind == "vacancy" else 101
        try:
            await h.send(actor, "/start")
            if kind == "team":
                await h.send(actor, "Создать команду")
                await h.send(actor, "[ТЕСТ] Сохранённое название")
            elif kind == "vacancy":
                await h.callback(actor, f"team:place:{team}")
                await h.click(actor, "Бэкенд-разработчик")
                await h.send(actor, "[ТЕСТ] Сохранённые задачи")
            else:
                await h.send(actor, "Команды")
                await h.click(actor, "Изменить фильтры")
                await h.click(actor, "Дизайнер")
        finally:
            await h.close()
        h = TelegramHarness(Service(service.config))
        try:
            await h.send(actor, "/start")
            await h.click(actor, "Продолжить заполнение")
            if kind == "team":
                await h.send(actor, "[ТЕСТ] Сохранённая тема")
                await h.click(actor, "Сохранить")
                assert service.team(service.membership(actor)["team_id"])["name"] == "[ТЕСТ] Сохранённое название"
            elif kind == "vacancy":
                await h.click(actor, "Python")
                await h.click(actor, "Готово")
                await h.click(actor, "Пропустить")
                await h.click(actor, "Да")
                await h.click(actor, "Сохранить")
                assert service.team(team)["vacancies"][-1]["tasks"] == "[ТЕСТ] Сохранённые задачи"
            else:
                await h.click(actor, "Пропустить")
                await h.click(actor, "Сохранить")
                assert "Найдено: 0" in h.last(actor).text
                await h.send(actor, "/start")
                await h.send(actor, "Команды")
                assert "Найдено: 0" in h.last(actor).text
        finally:
            await h.close()
    asyncio.run(scenario())


def test_restart_continues_profile_and_rejects_another_users_old_button(service):
    async def scenario():
        first = TelegramHarness(service)
        await first.send(1, "/start")
        await first.send(1, "Моя анкета")
        await first.click(1, "Заполнить анкету")
        await first.click(1, "Бэкенд-разработчик")
        old = first.last(1)
        callback = old.reply_markup.inline_keyboard[0][0].callback_data
        await first.close()
        second = TelegramHarness(Service(service.config))
        try:
            await second.callback(2, callback, old)
            assert "устар" in second.last(1).text.lower()
            await second.send(1, "/start")
            await second.click(1, "Продолжить заполнение")
            assert "Шаг 2/4" in second.last(1).text
            old = second.last(1)
            callback = old.reply_markup.inline_keyboard[0][0].callback_data
            await second.callback(1, callback, old)
            key = StorageKey(bot_id=second.bot.id, chat_id=1, user_id=1)
            data = await second.dispatcher.storage.get_data(key)
            assert data["form"]["values"]["role"] == "backend"
            assert data["form"]["step"] == 1
        finally:
            await second.close()
    asyncio.run(scenario())


def test_storage_all_drafts_filters_key_isolation_and_cleanup(service):
    async def scenario():
        storage = SQLiteStorage(service.db)
        for actor, kind in enumerate(("profile", "team", "vacancy"), 1):
            key = StorageKey(bot_id=1, chat_id=actor, user_id=actor)
            await storage.set_state(key, "FormState:filling")
            await storage.set_data(key, {"form": {"kind": kind, "step": 2}, "filters": {"role": "backend"}})
            new = SQLiteStorage(Service(service.config).db)
            assert await new.get_state(key) == "FormState:filling"
            assert (await new.get_data(key))["form"]["kind"] == kind
            assert (await new.get_data(key))["filters"]["role"] == "backend"
            assert await new.get_data(StorageKey(bot_id=2, chat_id=actor, user_id=actor)) == {}
        with service.db.connect(write=True) as c:
            c.execute("UPDATE fsm_sessions SET updated_at=?", (time.time() - 8 * 86400,))
        refreshed = SQLiteStorage(Service(service.config).db)
        assert await refreshed.get_data(StorageKey(bot_id=1, chat_id=1, user_id=1)) == {}
    asyncio.run(scenario())
