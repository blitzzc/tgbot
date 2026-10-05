import json

import pytest

from app.config import Config
from app.services.core import DomainError, Service
from tests.conftest import add_person, person, place_data, setup_place, team_data


def test_edit_does_not_store_roster_snapshots_or_internal_metadata(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    service.update_team(101, team_id, service.team(team_id))
    p = service.profile(202)
    service.set_visibility(202, False)
    service.save_profile(202, p)
    assert not service.profile(202)["visible"]
    with service.db.connect() as c:
        stored_team = json.loads(c.execute("SELECT data FROM teams WHERE id=?", (team_id,)).fetchone()[0])
        stored_profile = json.loads(c.execute("SELECT data FROM profiles WHERE user_id=202").fetchone()[0])
    assert set(stored_team) == {"name", "idea"}
    assert "user_id" not in stored_profile and "visible" not in stored_profile


@pytest.mark.parametrize("changes", [
    {"name": ""}, {"skills": []}, {"about": ""}, {"role": "invented"},
    {"links": "javascript:alert(1)"}, {"links": "https://"}, {"name": "x" * 61},
])
def test_invalid_profile_cannot_replace_saved_one(service, changes):
    add_person(service, 202)
    before = service.profile(202)
    with pytest.raises(DomainError):
        service.save_profile(202, person(**changes))
    assert service.profile(202) == before


def test_custom_normalized_skills_match_mandatory_requirements(service):
    _, place = setup_place(service, required=["Мой Навык"])
    add_person(service, 202, skills=["мой   навык"])
    assert service.search_people(101, place, True)[0]["profile"]["user_id"] == 202
    offer = service.create_offer(202, "application", 202, place, "Привет")
    assert service.resolve_offer(101, offer, "accept") == "accepted"
