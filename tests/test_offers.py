import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.services.core import DomainError
from tests.conftest import add_person, person, place_data, setup_place


def test_duplicate_pair_blocks_both_offer_types_and_double_accept(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    for actor, kind in ((202, "application"), (101, "invitation")):
        with pytest.raises(DomainError):
            service.create_offer(actor, kind, 202, place, "Привет")
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert service.resolve_offer(101, offer, "accept") == "accepted"
    assert len(service.team(team_id)["members"]) == 2
    # Устаревшая кнопка отмены не меняет завершённое предложение.
    assert service.resolve_offer(202, offer, "cancel") == "accepted"


@pytest.mark.parametrize("kind", ["application", "invitation"])
@pytest.mark.parametrize("action,expected", [("reject", "rejected"), ("cancel", "cancelled")])
def test_reject_cancel_are_terminal_without_membership(service, kind, action, expected):
    team_id, place = setup_place(service)
    add_person(service, 202)
    sender = 202 if kind == "application" else 101
    recipient = 101 if kind == "application" else 202
    offer = service.create_offer(sender, kind, 202, place, "Привет")
    assert service.resolve_offer(sender if action == "cancel" else recipient, offer, action) == expected
    assert service.resolve_offer(recipient, offer, "accept") == expected
    assert service.membership(202) is None
    assert service.vacancy(place)["status"] == "open"
    # Новое предложение после завершения разрешено.
    assert service.create_offer(sender, kind, 202, place, "Новое сообщение") != offer


@pytest.mark.parametrize("change", ["close", "pause", "requirements", "profile"])
def test_changed_mandatory_conditions_invalidate_offers(service, change):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    if change == "close":
        service.close_vacancy(101, place)
    elif change == "pause":
        service.set_recruitment(101, team_id, False)
    elif change == "requirements":
        service.update_vacancy(101, place, place_data(required=["Java"]))
    else:
        service.save_profile(202, person(skills=["Java"]))
    assert service.offer(202, offer)["status"] == "outdated"
    assert service.resolve_offer(101, offer, "accept") == "outdated"
    assert service.membership(202) is None


def concurrent_actions(service, operations):
    barrier = Barrier(len(operations))

    def worker(operation):
        barrier.wait()
        return service.resolve_offer(*operation)

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(worker, operations))


def test_concurrent_join_two_teams_only_one_succeeds(service):
    t1, p1 = setup_place(service)
    t2, p2 = setup_place(service, 303, "Вторая команда")
    add_person(service, 202)
    first = service.create_offer(202, "application", 202, p1, "Привет")
    second = service.create_offer(202, "application", 202, p2, "Привет")
    results = concurrent_actions(service, [(101, first, "accept"), (303, second, "accept")])
    assert sorted(results) == ["accepted", "outdated"]
    membership = service.membership(202)
    assert membership["team_id"] in {t1, t2}
    assert sorted([len(service.team(t1)["members"]), len(service.team(t2)["members"])]) == [1, 2]
    assert sorted([service.vacancy(p1)["status"], service.vacancy(p2)["status"]]) == ["filled", "open"]


def test_concurrent_two_people_one_place_only_one_succeeds(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    add_person(service, 303)
    first = service.create_offer(202, "application", 202, place, "Привет")
    second = service.create_offer(303, "application", 303, place, "Привет")
    assert sorted(concurrent_actions(service, [(101, first, "accept"), (101, second, "accept")])) == ["accepted", "outdated"]
    assert sum(service.membership(user) is not None for user in (202, 303)) == 1
    assert len(service.team(team_id)["members"]) == 2


def test_transaction_rolls_back_membership_if_place_update_fails(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    with service.db.connect(write=True) as c:
        c.execute("CREATE TRIGGER simulate_failure BEFORE UPDATE ON vacancies BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.resolve_offer(101, offer, "accept")
    assert service.membership(202) is None
    assert service.offer(202, offer)["status"] == "pending"
    assert service.vacancy(place)["status"] == "open"


def test_accept_rechecks_capacity_and_requirements_in_transaction(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    # Моделируем состояние, изменившееся до нажатия старой кнопки.
    for user in (303, 404, 505):
        add_person(service, user)
        with service.db.connect(write=True) as c:
            c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,'backend')", (user, team_id))
    with pytest.raises(DomainError, match="свободных"):
        service.resolve_offer(101, offer, "accept")
    assert service.membership(202) is None
