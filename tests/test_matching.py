import pytest

from app.catalogs import normalize_skill
from app.services.core import DomainError
from tests.conftest import add_person, person, place_data, setup_place


def test_normalization_aliases_and_distinct_languages(service):
    assert normalize_skill("  POSTGRES  ") == normalize_skill("PostgreSQL")
    assert normalize_skill(" JS ") == normalize_skill("JavaScript")
    assert normalize_skill("Мой   Навык") == normalize_skill("мой навык")
    assert len({normalize_skill(s) for s in ["C", "C++", "C#"]}) == 3
    _, place = setup_place(service, required=["postgres"])
    add_person(service, 202, skills=["POSTGRESQL", "postgres"])
    assert len(service.search_people(101, place)) == 1
    with service.db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM profile_skills WHERE user_id=202").fetchone()[0] == 1


@pytest.mark.parametrize("changes", [
    {"skills": ["Java"]}, {"experience": "beginner"},
])
def test_hard_constraints_exclude_from_search_and_offers(service, changes):
    _, place = setup_place(service, beginner="no")
    add_person(service, 202, experience="experienced", **{k: v for k, v in changes.items() if k != "experience"})
    if "experience" in changes:
        service.save_profile(202, person(experience=changes["experience"]))
    assert service.search_people(101, place, True) == []
    assert service.search_teams(202, True)[0]["vacancy"] is None
    with pytest.raises(DomainError):
        service.create_offer(202, "application", 202, place, "Привет")


def test_hidden_profile_excluded_but_prior_application_remains_valid(service):
    _, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.set_visibility(202, False)
    assert service.search_people(101, place) == []
    with pytest.raises(DomainError):
        service.candidate(101, place, 202)
    assert service.offer(101, offer)["status"] == "pending"
    assert service.resolve_offer(101, offer, "accept") == "accepted"


def test_ranking_is_role_then_desired_stable(service):
    _, place = setup_place(service, required=[], desired=["SQL", "Git"])
    add_person(service, 202, role="frontend", extra_roles=["backend"], skills=["SQL", "Git"])
    add_person(service, 303, role="backend", skills=["Python"], goal="experience")
    add_person(service, 404, role="backend", skills=["SQL"], goal="experience")
    add_person(service, 505, role="backend", skills=["SQL"], goal="portfolio")
    add_person(service, 606, role="backend", skills=["SQL"], goal="portfolio")
    results = service.search_people(101, place, True)
    assert [item["profile"]["user_id"] for item in results] == [404, 505, 606, 303, 202]
    assert results[0]["score"] == (2, 1)
    assert "SQL" in ";".join(results[0]["why"])


def test_filters_use_all_selected_normalized_skills(service):
    _, place = setup_place(service, required=[], desired=["PostgreSQL", "Git"])
    add_person(service, 202, skills=["postgresql", "Git"], extra_roles=["frontend"])
    add_person(service, 303, skills=["Python"])
    assert len(service.search_people(101, place, filters={"skills": ["postgres", "git"], "role": "frontend"})) == 1
    assert service.search_teams(202, filters={"skills": ["java"]}) == []
    assert len(service.search_teams(202, filters={"skills": ["postgres"]})) == 1


def test_newcomer_without_projects_and_links_can_register(service):
    add_person(service, 202, skills=["Мой навык"])
    p = service.profile(202)
    assert p["projects"] == p["links"] == ""
    assert p["experience"] == "beginner"


def test_legacy_removed_fields_do_not_affect_matching(service):
    team_id, place = setup_place(service)
    import json
    # Данные из прежней версии остаются читаемыми, но удалённые поля не влияют на подбор.
    with service.db.connect(write=True) as c:
        data = json.loads(c.execute("SELECT data FROM teams WHERE id=?", (team_id,)).fetchone()[0])
        data.update(format="hybrid", goal="win", load="high")
        c.execute("UPDATE teams SET data=? WHERE id=?", (json.dumps(data), team_id))
        vacancy = json.loads(c.execute("SELECT data FROM vacancies WHERE id=?", (place,)).fetchone()[0])
        vacancy["windows"] = ["weekday_day"]
        c.execute("UPDATE vacancies SET data=? WHERE id=?", (json.dumps(vacancy), place))
    add_person(service, 202, format="online")
    add_person(service, 303, format="hybrid")
    assert [p["profile"]["user_id"] for p in service.search_people(101, place)] == [202, 303]
