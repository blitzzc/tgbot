"""FSM aiogram: один SQLite-файл, без открытых соединений между вызовами."""
import asyncio
import json
import time
from dataclasses import asdict

from aiogram.fsm.storage.base import BaseStorage


class SQLiteStorage(BaseStorage):
    def __init__(self, database):
        self.db = database

    @staticmethod
    def _key(key):
        return json.dumps(asdict(key), sort_keys=True, separators=(",", ":"))

    def _read(self, key):
        with self.db.connect() as c:
            row = c.execute("SELECT state,data FROM fsm_sessions WHERE key=?", (self._key(key),)).fetchone()
            return (row["state"], json.loads(row["data"])) if row else (None, {})

    def _write(self, key, field, value, merge=False):
        with self.db.connect(write=True) as c:
            identity = self._key(key)
            row = c.execute("SELECT state,data FROM fsm_sessions WHERE key=?", (identity,)).fetchone()
            state, data = (row["state"], json.loads(row["data"])) if row else (None, {})
            if field == "state":
                state = value
            elif merge:
                data.update(value)
            else:
                data = dict(value)
            if state is None and not data:
                c.execute("DELETE FROM fsm_sessions WHERE key=?", (identity,))
            else:
                c.execute("""INSERT INTO fsm_sessions(key,state,data,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET state=excluded.state,data=excluded.data,updated_at=excluded.updated_at""",
                          (identity, state, json.dumps(data, ensure_ascii=False), time.time()))
            return data.copy()

    async def set_state(self, key, state=None):
        await asyncio.to_thread(self._write, key, "state", state.state if hasattr(state, "state") else state)

    async def get_state(self, key):
        return (await asyncio.to_thread(self._read, key))[0]

    async def set_data(self, key, data):
        await asyncio.to_thread(self._write, key, "data", data)

    async def get_data(self, key):
        return (await asyncio.to_thread(self._read, key))[1]

    async def update_data(self, key, data):
        return await asyncio.to_thread(self._write, key, "data", data, True)

    async def close(self):
        pass
