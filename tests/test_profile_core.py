import asyncio
import pytest
from app.services.core import DomainError
from tests.telegram_harness import TelegramHarness


@pytest.mark.parametrize("extras", [False, True])
def test_four_steps_both_branches_and_stale_save_button(service, extras):
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(2, "/start")
            await h.callback(2, "profile:edit")
            assert "Шаг 1/4" in h.last(2).text
            await h.click(2, "Бэкенд-разработчик")
            await h.click(2, "Python")
            await h.click(2, "Готово")
            await h.send(2, "Пока учусь")
            await h.click(2, "Новичок")
            old = h.last(2)
            save = old.reply_markup.inline_keyboard[0][0].callback_data
            with pytest.raises(DomainError):
                service.profile(2)
            if extras:
                await h.click(2, "Дополнить анкету")
                await h.send(2, "Мой псевдоним")
                for _ in range(3):
                    await h.click(2, "Пропустить")
                await h.click(2, "Сохранить")
                assert service.profile(2)["name"] == "Мой псевдоним"
            else:
                await h.click(2, "Сохранить и перейти к поиску")
                assert "Команды" in h.last(2).text
                assert service.profile(2)["name"] == "Тест 2"
            await h.callback(2, save, old)
            assert "устарела" in h.last(2).text
            assert service.profile(2)["skills"] == ["Python"]
            assert service.profile(2)["projects"] == ""
        finally:
            await h.close()
    asyncio.run(scenario())
