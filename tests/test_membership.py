import pytest

from app.config import Config
from app.services.core import DomainError, Service
from tests.conftest import add_person, person, place_data, setup_place, team_data


def test_main_application_flow(service):
    team_id, place_id = setup_place(service)
    add_person(service, 202)
    assert service.team(team_id)["members"][0]["user_id"] == 101
    assert service.search_teams(202)[0]["team"]["id"] == team_id
    recommended = service.search_teams(202, True)[0]
    assert recommended["vacancy"]["id"] == place_id
    assert any("роль" in text for text in recommended["why"])
    assert service.search_people(101, place_id)[0]["profile"]["user_id"] == 202
    offer = service.create_offer(202, "application", 202, place_id, "Хочу сделать API")
    assert service.membership(202) is None  # Отправка не равна согласию капитана.
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert service.membership(202)["team_id"] == team_id
    assert len(service.team(team_id)["members"]) == 2
    assert service.vacancy(place_id)["status"] == "filled"
    another = service.create_vacancy(101, team_id, place_data())
    assert service.search_people(101, another) == []
    assert {n["user_id"] for n in service.pending_notifications()} == {101, 202}


def test_reverse_invitation_requires_participant_consent(service):
    team_id, place_id = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(101, "invitation", 202, place_id, "Приглашаю в команду")
    assert service.membership(202) is None
    with pytest.raises(DomainError):
        service.resolve_offer(101, offer, "accept")
    assert service.resolve_offer(202, offer, "accept") == "accepted"
    assert service.membership(202)["team_id"] == team_id


def test_multiple_proposals_become_outdated_and_creation_also_counts(service):
    team1, place1 = setup_place(service)
    team2, place2 = setup_place(service, 303, "Вторая команда")
    add_person(service, 202)
    a = service.create_offer(202, "application", 202, place1, "Привет")
    b = service.create_offer(303, "invitation", 202, place2, "Привет")
    service.resolve_offer(101, a, "accept")
    assert service.offer(202, b)["status"] == "outdated"
    assert service.resolve_offer(202, b, "accept") == "outdated"
    assert service.membership(202)["team_id"] == team1
    with pytest.raises(DomainError):
        service.create_team(202, team_data())
    service.leave_team(202, team1)
    new_offer = service.create_offer(202, "application", 202, place2, "Снова свободен")
    own = service.create_team(202, team_data("Своя команда"))
    assert service.offer(202, new_offer)["status"] == "outdated"
    assert service.membership(202)["team_id"] == own


def test_leave_does_not_reopen_and_captain_must_transfer(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    with pytest.raises(DomainError):
        service.leave_team(101, team_id)
    service.transfer_captain(101, team_id, 202)
    service.leave_team(101, team_id)
    assert service.team(team_id)["captain_id"] == 202
    assert len(service.team(team_id)["members"]) == 1
    assert service.vacancy(place)["status"] == "filled"
    with pytest.raises(DomainError):
        service.leave_team(101, team_id)


def test_capacity_counts_captain_and_open_places(tmp_path):
    service = Service(Config(max_team_size=2, database=str(tmp_path / "limit.db")))
    team_id, place = setup_place(service)
    with pytest.raises(DomainError):
        service.create_vacancy(101, team_id, place_data())
    service.close_vacancy(101, place)
    new_place = service.create_vacancy(101, team_id, place_data())
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, new_place, "Привет")
    service.resolve_offer(101, offer, "accept")
    with pytest.raises(DomainError):
        service.create_vacancy(101, team_id, place_data())
    assert len(service.team(team_id)["members"]) == 2


def test_disband_notifies_and_frees_everyone(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    new_place = service.create_vacancy(101, team_id, place_data())
    add_person(service, 303)
    pending = service.create_offer(303, "application", 303, new_place, "Привет")
    service.disband_team(101, team_id)
    assert service.membership(101) is None
    assert service.membership(202) is None
    assert service.offer(303, pending)["status"] == "outdated"
    assert {101, 202, 303} <= {n["user_id"] for n in service.pending_notifications()}
    with pytest.raises(DomainError):
        service.team(team_id)


def test_roles_do_not_overwrite_personal_profiles(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    before = service.profile(202)
    service.change_role(101, team_id, 202, "frontend")
    assert service.membership(202)["role"] == "frontend"
    assert service.profile(202) == before
    service.save_profile(202, person("Новое имя", about="Новый опыт"))
    member = next(p for p in service.team(team_id)["members"] if p["user_id"] == 202)
    assert member["name"] == "Новое имя" and member["about"] == "Новый опыт"


def test_contact_is_private_and_recipients_checked_atomically(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    assert service.membership(202)["shared_contact"] is None
    assert all("shared_contact" not in p for p in service.team(team_id)["members"])
    with pytest.raises(DomainError):
        service.share_contact(202, team_id, "@test", [101, 999])
    service.share_contact(202, team_id, "@test", [101])
    notifications = [n for n in service.pending_notifications() if "@test" in n["body"]]
    assert len(notifications) == 1 and notifications[0]["user_id"] == 101
    service.leave_team(202, team_id)
    with pytest.raises(DomainError):
        service.share_contact(202, team_id, "@test", [101])
