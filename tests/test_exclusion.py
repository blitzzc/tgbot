import asyncio
import pytest
from app.services.core import DomainError
from tests.conftest import setup_place, add_person
from tests.telegram_harness import TelegramHarness


def joined(service):
    team, place = setup_place(service, captain=1)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.resolve_offer(1, offer, "accept")
    return team, place, service.membership(2)["generation"]


def test_exclusion_rights_self_and_repeat_and_reapplication(service):
    team, place, generation = joined(service)
    add_person(service, 3)
    with pytest.raises(DomainError):
        service.exclude_member(3, team, 2, generation)
    with pytest.raises(DomainError):
        service.exclude_member(1, team, 1, service.membership(1)["generation"])
    service.exclude_member(1, team, 2, generation)
    assert service.membership(2) is None
    with pytest.raises(DomainError):
        service.exclude_member(1, team, 2, generation)
    offer = service.create_offer(2, "application", 2, None, "Снова", team_id=team)
    service.resolve_offer(1, offer, "accept")
    with pytest.raises(DomainError):
        service.exclude_member(1, team, 2, generation)
    assert service.membership(2)
    assert any("исключил" in n["body"] for n in service.pending_notifications())


def test_exclusion_confirm_and_old_button_through_ui(service):
    team, _, generation = joined(service)
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(1, "/start")
            await h.callback(1, f"team:exclude:{team}:2:{generation}")
            assert service.membership(2)
            old = h.last(1)
            await h.click(1, "Исключить")
            await h.callback(1, f"team:exclude_yes:{team}:2:{generation}", old)
            assert "изменился" in h.last(1).text
        finally:
            await h.close()
    asyncio.run(scenario())


def test_exclusion_and_notice_are_one_transaction(service, monkeypatch):
    team, _, generation = joined(service)
    def failure(*args):
        raise RuntimeError("Сбой записи очереди")
    monkeypatch.setattr(service, "_notify", failure)
    with pytest.raises(RuntimeError):
        service.exclude_member(1, team, 2, generation)
    assert service.membership(2)["generation"] == generation
