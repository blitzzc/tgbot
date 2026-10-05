import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        self._migrate_offers()

    def _migrate_offers(self):
        with self.connect() as source:
            columns = {row["name"] for row in source.execute("PRAGMA table_info(offers)")}
            if "team_id" not in columns:
                backup_path = Path(self.path + ".before-team-applications.bak")
                if not backup_path.exists():
                    backup = sqlite3.connect(backup_path)
                    try:
                        source.backup(backup)
                    finally:
                        backup.close()
        with self.connect(write=True) as c:
            columns = {row["name"] for row in c.execute("PRAGMA table_info(offers)")}
            if "team_id" not in columns:
                # Атомарное обновление старой базы: ID и история предложений сохраняются.
                schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
                create = schema.split("CREATE TABLE IF NOT EXISTS offers (", 1)[1].split(");", 1)[0]
                c.execute("CREATE TABLE offers_next (" + create + ")")
                c.execute("""INSERT INTO offers_next
                    (id,kind,user_id,team_id,vacancy_id,sender_id,message,status,reason,created_at,resolved_at)
                    SELECT o.id,o.kind,o.user_id,v.team_id,o.vacancy_id,o.sender_id,o.message,
                           o.status,o.reason,o.created_at,o.resolved_at
                    FROM offers o JOIN vacancies v ON v.id=o.vacancy_id""")
                c.execute("DROP TABLE offers")
                c.execute("ALTER TABLE offers_next RENAME TO offers")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_pending_offer ON offers(user_id,vacancy_id) WHERE status='pending'")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_pending_team_offer ON offers(user_id,team_id) WHERE status='pending' AND vacancy_id IS NULL")
            c.execute("CREATE INDEX IF NOT EXISTS offers_place ON offers(vacancy_id,status)")
            c.execute("CREATE INDEX IF NOT EXISTS offers_team ON offers(team_id,status)")

    @contextmanager
    def connect(self, write=False):
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()
