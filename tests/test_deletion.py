import asyncio
import pytest
from app.services.core import DomainError
from tests.conftest import setup_place, add_person
from tests.telegram_harness import TelegramHarness


def test_delete_member_profile_offers_notices_contact_and_new_profile(service):
    team, place = setup_place(service)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    service.share_contact(2, team, "@private_user", [101])
    service.delete_data(2)
    assert service.membership(2) is None
    assert len(service.team(team)["members"]) == 1
    assert service.vacancy(place)["status"] == "filled"
    with pytest.raises(DomainError):
        service.profile(2)
    with pytest.raises(DomainError):
        service.offer(101, offer)
    with service.db.connect() as c:
        assert not c.execute("SELECT 1 FROM users WHERE id=2").fetchone()
        assert not c.execute("SELECT 1 FROM notifications WHERE user_id=2 OR body LIKE '%@private_user%'").fetchone()
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
    add_person(service, 2)
    assert service.profile(2)


def test_captain_must_transfer_or_disband_then_can_delete(service):
    team, _ = setup_place(service)
    with pytest.raises(DomainError, match="передайте"):
        service.delete_data(101)
    assert service.profile(101)
    service.disband_team(101, team)
    service.delete_data(101)
    with service.db.connect() as c:
        assert c.execute("SELECT captain_id FROM teams WHERE id=?", (team,)).fetchone()[0] == 0
        assert not c.execute("PRAGMA foreign_key_check").fetchall()


def test_double_confirmation_other_user_cancel_and_stale_after_new_profile(service):
    add_person(service, 2)
    add_person(service, 3)
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(2, "Мои данные")
            await h.click(2, "Удалить мои данные")
            await h.click(2, "Продолжить удаление")
            last = h.last(2)
            token = last.reply_markup.inline_keyboard[0][0].callback_data
            assert service.profile(2)
            await h.send(3, "/start")
            await h.callback(3, token)
            assert service.profile(2) and service.profile(3)
            await h.click(2, "Отмена")
            await h.callback(2, token, last)
            assert service.profile(2)
            await h.send(2, "Мои данные")
            await h.click(2, "Удалить мои данные")
            await h.click(2, "Продолжить удаление")
            last = h.last(2)
            token = last.reply_markup.inline_keyboard[0][0].callback_data
            await h.click(2, "Удалить мои данные окончательно")
            with pytest.raises(DomainError):
                service.profile(2)
            add_person(service, 2)
            await h.callback(2, token, last)
            assert service.profile(2)
        finally:
            await h.close()
    asyncio.run(scenario())
