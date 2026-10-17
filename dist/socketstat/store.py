import sqlite3
from contextlib import contextmanager

RETENTION = 14 * 24 * 60 * 60


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS observations (
                device_id TEXT NOT NULL,
                scheduled_at INTEGER NOT NULL,
                checked_at REAL NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('online','offline','unknown')),
                error_code TEXT,
                PRIMARY KEY (device_id, scheduled_at)
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS observations_time ON observations(scheduled_at)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, device_id, slot, checked_at, state, error=None):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?)',
                       (device_id, slot, checked_at, state, error))

    def cleanup(self, now):
        with self.connect() as db:
            db.execute('DELETE FROM observations WHERE scheduled_at < ?', (now - RETENTION,))

    def read(self, device_id, start, end):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                '''SELECT * FROM observations WHERE device_id = ?
                   AND scheduled_at >= ? AND scheduled_at < ? ORDER BY scheduled_at''',
                (device_id, start - 60, end))]

    def latest(self, device_id):
        with self.connect() as db:
            row = db.execute('''SELECT * FROM observations WHERE device_id = ?
                ORDER BY scheduled_at DESC LIMIT 1''', (device_id,)).fetchone()
            return dict(row) if row else None
