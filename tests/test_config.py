import pytest

from app.config import Config
from app.services.core import DomainError, Service
from tests.conftest import add_person, setup_place


@pytest.mark.parametrize("changes", [
    {"max_team_size": 2.5}, {"max_team_size": 1}, {"max_team_size": True},
    {"name": ""}, {"timezone": "Unknown/Zone"}, {"database": ""},
])
def test_invalid_config_is_rejected(changes):
    with pytest.raises(ValueError):
        Config(**changes)


def test_hidden_profile_cannot_receive_recommendations_but_can_browse(service):
    setup_place(service)
    add_person(service, 202)
    service.set_visibility(202, False)
    with pytest.raises(DomainError, match="покажите анкету"):
        service.search_teams(202, True)
    assert service.search_teams(202)


def test_removed_fields_are_not_required_or_saved(service):
    add_person(service, 202)
    profile = service.profile(202)
    for key in ("format", "goal", "load", "windows", "topics"):
        assert key not in profile
    service.save_profile(202, profile)
