import pytest

from app.services.core import DomainError
from tests.conftest import add_person, place_data, setup_place, team_data


@pytest.mark.parametrize("operation", [
    lambda s, t, p, o: s.create_vacancy(999, t, place_data()),
    lambda s, t, p, o: s.update_vacancy(999, p, place_data()),
    lambda s, t, p, o: s.close_vacancy(999, p),
    lambda s, t, p, o: s.update_team(999, t, team_data()),
    lambda s, t, p, o: s.set_recruitment(999, t, False),
    lambda s, t, p, o: s.search_people(999, p),
    lambda s, t, p, o: s.candidate(999, p, 202),
    lambda s, t, p, o: s.create_offer(999, "invitation", 202, p, "Привет"),
    lambda s, t, p, o: s.create_offer(999, "application", 202, p, "Привет"),
    lambda s, t, p, o: s.offer(999, o),
    lambda s, t, p, o: s.resolve_offer(999, o, "accept"),
    lambda s, t, p, o: s.resolve_offer(999, o, "reject"),
    lambda s, t, p, o: s.resolve_offer(999, o, "cancel"),
    lambda s, t, p, o: s.transfer_captain(999, t, 202),
    lambda s, t, p, o: s.change_role(999, t, 101, "design"),
    lambda s, t, p, o: s.leave_team(999, t),
    lambda s, t, p, o: s.disband_team(999, t),
    lambda s, t, p, o: s.share_contact(999, t, "@test", [101]),
])
def test_outsider_cannot_mutate_or_read_private_proposals(service, operation):
    team_id, place = setup_place(service)
    add_person(service, 202)
    add_person(service, 999)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    with pytest.raises(DomainError):
        operation(service, team_id, place, offer)
    assert service.vacancy(place)["status"] == "open"
    assert service.offer(202, offer)["status"] == "pending"
    assert len(service.team(team_id)["members"]) == 1


def test_sender_cannot_decide_and_recipient_cannot_cancel(service):
    _, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    with pytest.raises(DomainError):
        service.resolve_offer(202, offer, "accept")
    with pytest.raises(DomainError):
        service.resolve_offer(101, offer, "cancel")


def test_transferred_captain_rights_apply_to_pending_proposals(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    accepted = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, accepted, "accept")
    next_place = service.create_vacancy(101, team_id, place_data())
    add_person(service, 303)
    pending = service.create_offer(303, "application", 303, next_place, "Привет")
    service.transfer_captain(101, team_id, 202)
    with pytest.raises(DomainError):
        service.resolve_offer(101, pending, "accept")
    assert service.resolve_offer(202, pending, "accept") == "accepted"
