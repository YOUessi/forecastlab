"""SQLite index plus immutable, per-stage JSON snapshots for replay."""
import json
import sqlite3
from pathlib import Path
from threading import RLock
from .schemas import RunRecord, utcnow


class RunStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.snapshots = self.directory / "runs"
        self.snapshots.mkdir(exist_ok=True)
        self.db = self.directory / "forecastlab.sqlite3"
        self.lock = RLock()
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, data TEXT NOT NULL)")
            con.execute("CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at DESC)")

    def connect(self):
        con = sqlite3.connect(self.db, timeout=20)
        con.row_factory = sqlite3.Row
        return con

    def save(self, record: RunRecord, snapshot: bool = True):
        data = record.model_dump_json()
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO runs(run_id,status,started_at,data) VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,data=excluded.data", (record.run_id, record.status, record.started_at.isoformat(), data))
        if snapshot:
            folder = self.snapshots / record.run_id
            folder.mkdir(exist_ok=True)
            stage = record.stage.replace("/", "_")
            temp = folder / f".{stage}.tmp"
            temp.write_text(data, encoding="utf-8")
            temp.replace(folder / f"{stage}.json")

    def get(self, run_id: str) -> RunRecord | None:
        with self.lock, self.connect() as con:
            row = con.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return RunRecord.model_validate_json(row["data"]) if row else None

    def list(self, limit: int = 50) -> list[RunRecord]:
        with self.lock, self.connect() as con:
            rows = con.execute("SELECT data FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [RunRecord.model_validate_json(row["data"]) for row in rows]

    def mark_interrupted(self):
        for run in self.list(1000):
            if run.status in ("queued", "running"):
                run.status = "interrupted"
                run.stage = "interrupted"
                run.errors.append("服务重启时任务未完成；可从历史记录重新运行。")
                run.finished_at = utcnow()
                self.save(run)
