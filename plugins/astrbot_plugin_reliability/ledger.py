"""Small idempotency boundary using SQLite's atomic unique constraint."""
from pathlib import Path
import sqlite3
import time


class MessageLedger:
    def __init__(self, path: Path, ttl: int = 3600):
        self.path = path
        self.ttl = ttl
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS received (scope TEXT, message_id TEXT, seen_at REAL, PRIMARY KEY(scope,message_id))")
            db.execute("CREATE INDEX IF NOT EXISTS received_time ON received(seen_at)")

    def claim(self, scope: str, message_id: str, *, now=None) -> bool:
        if not message_id:
            return True
        timestamp = time.time() if now is None else now
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("DELETE FROM received WHERE seen_at < ?", (timestamp - self.ttl,))
            cursor = db.execute("INSERT OR IGNORE INTO received VALUES (?,?,?)", (scope, message_id, timestamp))
            return cursor.rowcount == 1
