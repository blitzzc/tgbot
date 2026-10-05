import asyncio
import pytest
from tests.conftest import add_person
from tests.telegram_harness import TelegramHarness


@pytest.mark.parametrize("skip", [True, False])
def test_theme_single_confirmation_return_and_old_button(service, skip):
    add_person(service, 2)
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(2, "Создать команду")
            await h.send(2, "[ТЕСТ] Команда с темой")
            await h.click(2, "Пропустить")
            assert "Пропустить без темы?" in h.last(2).text
            old = h.last(2)
            old_button = old.reply_markup.inline_keyboard[0][0].callback_data
            await h.send(3, "/start")
            await h.callback(3, old_button)
            assert service.membership(2) is None
            if skip:
                await h.click(2, "Да, пропустить")
            else:
                await h.click(2, "Указать тему")
                await h.send(2, "Помощь студентам")
            assert "Предпросмотр" in h.last(2).text
            await h.click(2, "Сохранить")
            team = service.team(service.membership(2)["team_id"])
            assert team["idea"] == ("Тему выберем вместе" if skip else "Помощь студентам")
            await h.callback(2, old_button, old)
            assert "устарела" in h.last(2).text
            assert len(service.search_teams(3)) == 1
        finally:
            await h.close()
    asyncio.run(scenario())
