import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from app.config import Config
from app.services.core import DomainError, Service
from tests.conftest import add_person, person, place_data, setup_place, team_data
from tests.telegram_harness import TelegramHarness, fill_profile
from tests.test_offers import concurrent_actions


def bare_team(service, captain=101, name="Команда без позиций"):
    add_person(service, captain)
    return service.create_team(captain, team_data(name))


def apply(service, user_id, team_id):
    return service.create_offer(user_id, "application", user_id, None, "Хочу присоединиться", team_id)


def test_team_without_positions_is_visible_to_anyone(service):
    team_id = bare_team(service)
    # Даже без анкеты можно посмотреть команду, но сначала нужно заполнить анкету для заявки.
    item = service.search_teams(999)[0]
    assert item["team"]["id"] == team_id and item["vacancy"] is None
    assert not item["can_apply"]
    assert item["application_status"] == "Сначала заполните анкету"
    add_person(service, 202)
    assert service.search_teams(202)[0]["can_apply"]
    assert service.search_teams(202, True)[0]["vacancy"] is None
    # Текущее членство не мешает просмотру составов.
    assert service.search_teams(101)[0]["team"]["id"] == team_id
    assert not service.search_teams(101)[0]["can_apply"]


def test_general_application_join_uses_person_role_and_updates_status(service):
    team_id = bare_team(service)
    add_person(service, 202, role="frontend")
    offer = apply(service, 202, team_id)
    assert service.offer(101, offer)["vacancy"] is None
    assert service.team_application_status(202, team_id) == (False, "Заявка уже отправлена")
    assert service.membership(202) is None
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert service.membership(202)["role"] == "frontend"
    assert len(service.team(team_id)["members"]) == 2
    assert service.team_application_status(202, team_id) == (False, "Вы уже состоите в команде")


def test_general_application_does_not_require_position_skills(service):
    team_id, place = setup_place(service, required=["Java"], beginner="no")
    add_person(service, 202, skills=["Python"], experience="beginner")
    with pytest.raises(DomainError):
        service.create_offer(202, "application", 202, place, "Привет")
    offer = apply(service, 202, team_id)
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert service.vacancy(place)["status"] == "open"


@pytest.mark.parametrize("action,status", [("cancel", "cancelled"), ("reject", "rejected")])
def test_general_cancel_reject_and_duplicate_rules(service, action, status):
    team_id = bare_team(service)
    add_person(service, 202)
    offer = apply(service, 202, team_id)
    with pytest.raises(DomainError):
        apply(service, 202, team_id)
    actor = 202 if action == "cancel" else 101
    assert service.resolve_offer(actor, offer, action) == status
    assert service.resolve_offer(101, offer, "accept") == status
    assert service.membership(202) is None
    assert apply(service, 202, team_id) != offer


@pytest.mark.parametrize("action", ["accept", "reject", "cancel"])
def test_general_offer_outsider_has_no_access(service, action):
    team_id = bare_team(service)
    add_person(service, 202)
    offer = apply(service, 202, team_id)
    with pytest.raises(DomainError):
        service.offer(999, offer)
    with pytest.raises(DomainError):
        service.resolve_offer(999, offer, action)
    assert service.offer(202, offer)["status"] == "pending"


def test_general_sender_cannot_accept_and_invitation_needs_consent(service):
    team_id = bare_team(service)
    add_person(service, 202)
    offer = apply(service, 202, team_id)
    with pytest.raises(DomainError):
        service.resolve_offer(202, offer, "accept")
    with pytest.raises(DomainError):
        service.create_offer(101, "application", 202, None, "Привет", team_id)
    with pytest.raises(DomainError):
        service.create_offer(101, "invitation", 202, None, "Привет", team_id)
    assert service.membership(202) is None


def test_last_place_concurrent_general_applications_only_one_join(tmp_path):
    service = Service(Config(max_team_size=2, database=str(tmp_path / "last.db")))
    team_id = bare_team(service)
    add_person(service, 202)
    add_person(service, 303)
    first, second = apply(service, 202, team_id), apply(service, 303, team_id)
    assert sorted(concurrent_actions(service, [(101, first, "accept"), (101, second, "accept")])) == ["accepted", "outdated"]
    assert len(service.team(team_id)["members"]) == 2
    item = service.search_teams(999)[0]
    assert item["application_status"] == "Команда заполнена"
    assert not item["can_apply"]
    loser = 202 if service.membership(202) is None else 303
    with pytest.raises(DomainError):
        apply(service, loser, team_id)


def test_general_two_teams_conflict_invalidates_position_offers_too(service):
    first_team = bare_team(service)
    second_team, place = setup_place(service, 303, "Вторая команда")
    add_person(service, 202)
    first = apply(service, 202, first_team)
    second = apply(service, 202, second_team)
    positional = service.create_offer(202, "application", 202, place, "Привет")
    assert sorted(concurrent_actions(service, [(101, first, "accept"), (303, second, "accept")])) == ["accepted", "outdated"]
    assert service.offer(202, positional)["status"] == "outdated"
    assert service.membership(202)["team_id"] in {first_team, second_team}


@pytest.mark.parametrize("change", ["pause", "disband"])
def test_closed_team_general_offers_outdated(service, change):
    team_id = bare_team(service)
    add_person(service, 202)
    offer = apply(service, 202, team_id)
    if change == "pause":
        service.set_recruitment(101, team_id, False)
        assert service.search_teams(202)[0]["application_status"] == "Набор приостановлен"
    else:
        service.disband_team(101, team_id)
        assert service.search_teams(202) == []
    assert service.offer(202, offer)["status"] == "outdated"
    assert service.resolve_offer(101, offer, "accept") == "outdated"
    with pytest.raises(DomainError):
        apply(service, 202, team_id)


def test_full_team_closes_positions_and_other_general_requests(tmp_path):
    service = Service(Config(max_team_size=2, database=str(tmp_path / "capacity.db")))
    team_id, place = setup_place(service)
    add_person(service, 202)
    add_person(service, 303)
    specific = service.create_offer(303, "application", 303, place, "Привет")
    general = apply(service, 202, team_id)
    other = apply(service, 303, team_id)
    service.resolve_offer(101, general, "accept")
    assert service.vacancy(place)["status"] == "closed"
    assert service.offer(303, specific)["status"] == service.offer(303, other)["status"] == "outdated"


def test_old_database_migration_keeps_history_and_members(tmp_path):
    path = tmp_path / "old.db"
    schema = Path("app/schema.sql").read_text(encoding="utf-8")
    old_schema = schema.replace("    team_id INTEGER NOT NULL REFERENCES teams(id),\n    vacancy_id INTEGER REFERENCES vacancies(id),", "    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),")
    with sqlite3.connect(path) as c:
        c.executescript(old_schema)
        for user in (101, 202):
            c.execute("INSERT INTO users VALUES(?,?)", (user, user))
            c.execute("INSERT INTO profiles(user_id,data) VALUES(?,?)", (user, json.dumps(person())))
        c.execute("INSERT INTO teams(id,captain_id,data) VALUES(1,101,?)", (json.dumps(team_data()),))
        c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(101,1,'backend')")
        c.execute("INSERT INTO vacancies(id,team_id,data) VALUES(1,1,?)", (json.dumps(place_data()),))
        c.execute("INSERT INTO offers(id,kind,user_id,vacancy_id,sender_id,message) VALUES(1,'application',202,1,202,'Старая заявка')")
    service = Service(Config(database=str(path)))
    assert service.offer(101, 1)["message"] == "Старая заявка"
    assert service.offer(101, 1)["team_id"] == 1
    assert service.membership(101)["team_id"] == 1
    assert Path(str(path) + ".before-team-applications.bak").is_file()
    assert apply(service, 202, 1) == 2
    assert Service(service.config).offer(202, 1)["vacancy_id"] == 1
    with service.db.connect() as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


async def general_application_flow(service):
    h = TelegramHarness(service)
    try:
        await fill_profile(h, 101, "[ТЕСТ] Капитан")
        await h.send(101, "Моя команда / Создать команду")
        await h.click(101, "Создать команду")
        await h.send(101, "[ТЕСТ] Команда без позиций")
        await h.click(101, "Пропустить")
        await h.click(101, "Да, пропустить")
        await h.click(101, "Сохранить")
        team_id = service.membership(101)["team_id"]
        assert service.team(team_id)["vacancies"] == []
        await fill_profile(h, 202, "[ТЕСТ] Участник")
        await h.send(202, "Команды")
        assert "Можно отправить заявку" in h.last(202).text
        await h.click(202, "1. Команда и состав")
        assert "Состав: 1/4" in h.last(202).text and "[ТЕСТ] Капитан" in h.last(202).text
        await h.click(202, "Подать заявку в команду")
        await h.send(202, "Хочу присоединиться без выбора позиции")
        await h.click(202, "Отправить")
        offer = service.offers(202)[0]["id"]
        await h.send(202, "Команды")
        assert "Заявка уже отправлена" in h.last(202).text
        await h.send(101, "Заявки и приглашения")
        await h.click(101, f"Открыть №{offer}")
        await h.click(101, "Принять")
        await h.send(202, "Команды")
        assert "Вы уже состоите в команде" in h.last(202).text
        await h.click(202, "1. Команда и состав")
        assert "Состав: 2/4" in h.last(202).text
        assert service.membership(202)["team_id"] == team_id
        return h.session.sent
    finally:
        await h.close()


def test_general_application_flow_through_telegram_ui(service):
    asyncio.run(general_application_flow(service))
