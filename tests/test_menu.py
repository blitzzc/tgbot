import asyncio
import pytest
from app.services.core import DomainError
from tests.conftest import add_person, setup_place
from tests.telegram_harness import TelegramHarness


def test_menu_for_all_states_and_mutations(service):
    assert service.menu_labels(2) == ["Заполнить анкету", "Мои данные", "Настройки и помощь"]
    team, place = setup_place(service)
    add_person(service, 2)
    free = service.menu_labels(2)
    assert all(label in free for label in ["Найти команду", "Создать команду", "Команды"])
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    member = service.menu_labels(2)
    assert "Моя команда" in member and "Создать команду" not in member
    assert "Найти команду" not in member and "Места и заявки" not in member
    assert "Места и заявки" in service.menu_labels(101)
    service.transfer_captain(101, team, 2)
    assert "Места и заявки" in service.menu_labels(2)
    assert "Места и заявки" not in service.menu_labels(101)
    service.leave_team(101, team)
    assert "Создать команду" in service.menu_labels(101)


def test_reply_keyboard_matches_state_and_old_captain_menu_checks_rights(service):
    team, _ = setup_place(service)
    add_person(service, 2)
    async def scenario():
        h = TelegramHarness(service)
        try:
            for actor in (101, 2, 3):
                await h.send(actor, "/start")
                markup = h.session.requests[-1].reply_markup
                assert [b.text for row in markup.keyboard for b in row] == service.menu_labels(actor)
            await h.send(2, "Места и заявки")
            assert "капитану" in h.last(2).text or "не состоите" in h.last(2).text
            await h.send(101, "Места и заявки")
            assert "Место №" in str(h.last(101).reply_markup)
            service.disband_team(101, team)
            await h.send(101, "Места и заявки")
            assert "не состоите" in h.last(101).text
        finally:
            await h.close()
    asyncio.run(scenario())
