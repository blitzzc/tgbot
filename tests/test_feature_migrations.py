import sqlite3
from pathlib import Path
from app.services.core import Service
from tests.conftest import add_person, setup_place


def test_old_database_backup_preserves_ids_history_and_repeat_is_safe(service):
    team, place = setup_place(service)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    with service.db.connect(write=True) as c:
        c.execute("DROP TABLE fsm_sessions")
        c.execute("DROP INDEX offers_sender_time")
        for table, columns in {
            "memberships": ("generation",), "vacancies": ("version",),
            "offers": ("sent_at",),
            "notifications": ("sending_at", "claim_token", "uncertain", "subjects"),
        }.items():
            for column in columns:
                c.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    migrated = Service(service.config)
    backup_path = Path(service.config.database + ".before-fsm.bak")
    assert backup_path.is_file()
    with sqlite3.connect(backup_path) as old:
        assert old.execute("SELECT id,status FROM offers").fetchone() == (offer, "accepted")
        assert "generation" not in {r[1] for r in old.execute("PRAGMA table_info(memberships)")}
        assert not old.execute("SELECT 1 FROM sqlite_master WHERE name='fsm_sessions'").fetchone()
    assert migrated.offer(101, offer)["status"] == "accepted"
    assert migrated.membership(2)["team_id"] == team
    generation = migrated.membership(2)["generation"]
    assert generation
    again = Service(service.config)
    assert again.membership(2)["generation"] == generation
    assert again.vacancy(place)["status"] == "filled"
    with again.db.connect() as c:
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
        assert c.execute("SELECT sent_at FROM offers WHERE id=?", (offer,)).fetchone()[0] > 0
