import pytest

from app.config import Config
from app.services.core import Service


def person(name="Участник", **changes):
    data = {
        "name": name, "role": "backend", "extra_roles": [], "skills": ["Python", "SQL", "PostgreSQL"],
        "about": "Учусь, делал учебные проекты", "experience": "beginner",
        "projects": "", "links": "",
    }
    data.update(changes)
    return data


def team_data(name="Тестовая команда", **changes):
    data = {"name": name, "idea": "Тему выберем вместе"}
    data.update(changes)
    return data


def place_data(**changes):
    data = {"role": "backend", "tasks": "Сделать API", "required": ["Python"], "desired": ["PostgreSQL", "Git"], "windows": ["weekend"], "beginner": "yes"}
    data.update(changes)
    return data


@pytest.fixture
def service(tmp_path):
    return Service(Config(database=str(tmp_path / "test.db")))


def add_person(service, user_id, **changes):
    service.register(user_id, user_id)
    service.save_profile(user_id, person(f"Тестовый участник {user_id}", **changes))


def setup_place(service, captain=101, name="Тестовая команда", **changes):
    add_person(service, captain)
    team_id = service.create_team(captain, team_data(name))
    place_id = service.create_vacancy(captain, team_id, place_data(**changes))
    return team_id, place_id
