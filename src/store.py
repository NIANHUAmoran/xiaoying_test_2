import json
import sqlite3
from contextlib import contextmanager

from .domain import fingerprint, initial_state


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, catalog_hash TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans (task_id TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def register(self, request, world):
        catalog = {key: world[key] for key in ["materials", "variants", "fees", "simulation_start"]}
        with self.transaction():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (request["request_id"],)).fetchone()
            if row:
                if row["request_hash"] != fingerprint(request):
                    raise ValueError("同一 request_id 不可修改原始请求")
                if row["catalog_hash"] != fingerprint(catalog):
                    raise ValueError("任务素材或计价目录发生变化，请使用新 request_id；故障恢复不受此限制")
            else:
                state = initial_state(request, world)
                self.db.execute("INSERT INTO tasks VALUES (?,?,?,?)", (request["request_id"], fingerprint(request),
                                fingerprint(catalog), json.dumps(state, ensure_ascii=False)))

    def get(self, task_id):
        row = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        return json.loads(row["state"])

    def put(self, task_id, state):
        self.db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state, ensure_ascii=False), task_id))

    def apply(self, task_id, callback):
        with self.transaction():
            state = self.get(task_id)
            result = callback(state)
            self.put(task_id, state)
        return result
