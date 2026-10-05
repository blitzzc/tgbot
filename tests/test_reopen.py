import asyncio
import pytest
from app.services.core import DomainError
from tests.conftest import setup_place, add_person, place_data
from tests.telegram_harness import TelegramHarness


@pytest.mark.parametrize("copy", [False, True])
def test_reuse_rights_history_and_old_version(service, copy):
    team, place = setup_place(service)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.close_vacancy(101, place)
    old = service.vacancy(place)
    with pytest.raises(DomainError):
        service.reuse_vacancy(2, place, old["version"], copy)
    new_id = service.reuse_vacancy(101, place, old["version"], copy)
    assert service.vacancy(new_id)["status"] == "open"
    assert service.validate_vacancy(service.vacancy(new_id)) == service.validate_vacancy(old)
    assert service.offer(2, offer)["status"] == "outdated"
    with pytest.raises(DomainError):
        service.reuse_vacancy(101, place, old["version"], copy)


def test_filled_reopen_capacity_and_paused(service):
    team, place = setup_place(service)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    service.leave_team(2, team)
    version = service.vacancy(place)["version"]
    for _ in range(3):
        service.create_vacancy(101, team, place_data())
    with pytest.raises(DomainError, match="Лимит"):
        service.reuse_vacancy(101, place, version)
    extra = service.team(team)["vacancies"][-1]["id"]
    service.close_vacancy(101, extra)
    service.set_recruitment(101, team, False)
    with pytest.raises(DomainError, match="возобновите"):
        service.reuse_vacancy(101, place, version)
    service.set_recruitment(101, team, True)
    service.reuse_vacancy(101, place, version)
    assert service.vacancy(place)["filled_by"] is None


def test_copy_old_ui_button_cannot_create_duplicates(service):
    _, place = setup_place(service)
    service.close_vacancy(101, place)
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(101, "/start")
            await h.callback(101, f"place:view:{place}")
            old = h.last(101)
            data = next(b.callback_data for row in old.reply_markup.inline_keyboard for b in row if b.text == "Создать копию места")
            await h.click(101, "Создать копию места")
            await h.callback(101, data, old)
            assert "изменилось" in h.last(101).text
            assert len(service.team(1)["vacancies"]) == 2
        finally:
            await h.close()
    asyncio.run(scenario())
