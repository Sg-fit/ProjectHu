"""SQLite persistence. Raw output is always persisted; every number in the
writeup must be regenerable from this database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    model        TEXT NOT NULL,
    framing      TEXT NOT NULL,
    prompt_id    TEXT NOT NULL,
    run_idx      INTEGER NOT NULL,
    ts           TEXT NOT NULL,
    raw_output   TEXT,
    params_json  TEXT,
    served_model TEXT,
    stop_reason  TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd     REAL DEFAULT 0,
    latency_ms   REAL,
    error        TEXT,
    UNIQUE(model, prompt_id, run_idx)
);
CREATE TABLE IF NOT EXISTS extractions (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    ecosystem    TEXT NOT NULL,
    name_raw     TEXT NOT NULL,
    name_norm    TEXT NOT NULL,
    surface_form TEXT NOT NULL,
    resolution   TEXT NOT NULL,
    context      TEXT
);
CREATE INDEX IF NOT EXISTS ix_extr_name ON extractions(ecosystem, name_norm);
CREATE INDEX IF NOT EXISTS ix_extr_run ON extractions(run_id);
CREATE TABLE IF NOT EXISTS oracle (
    ecosystem     TEXT NOT NULL,
    name_norm     TEXT NOT NULL,
    bucket        TEXT NOT NULL,
    exists_       INTEGER NOT NULL,
    first_release TEXT,
    last_release  TEXT,
    downloads_30d INTEGER,
    latest_version TEXT,
    summary       TEXT,
    checked_at    TEXT NOT NULL,
    PRIMARY KEY (ecosystem, name_norm)
);
-- Every network lookup, timestamped (hard rule 4: claims are valid only as of check time).
CREATE TABLE IF NOT EXISTS lookups (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    ecosystem  TEXT NOT NULL,
    name_norm  TEXT NOT NULL,
    url        TEXT NOT NULL,
    status     INTEGER,
    latency_ms REAL,
    error      TEXT
);
CREATE TABLE IF NOT EXISTS verdicts (
    extraction_id  INTEGER NOT NULL REFERENCES extractions(id),
    verdict        TEXT NOT NULL,
    reason         TEXT,
    policy_version TEXT NOT NULL,
    PRIMARY KEY (extraction_id, policy_version)
);
CREATE TABLE IF NOT EXISTS shim_eval (
    id         INTEGER PRIMARY KEY,
    case_set   TEXT NOT NULL,
    name       TEXT NOT NULL,
    ecosystem  TEXT NOT NULL DEFAULT 'pypi',
    truth      TEXT NOT NULL,
    verdict    TEXT NOT NULL,
    reason     TEXT,
    latency_ms REAL,
    cache      TEXT,
    policy_version TEXT,
    ts         TEXT
);
-- Hand labels: misattribution (exists, but not what the model described) and extractor audit.
CREATE TABLE IF NOT EXISTS labels (
    id            INTEGER PRIMARY KEY,
    extraction_id INTEGER REFERENCES extractions(id),
    ecosystem     TEXT,
    name_norm     TEXT,
    label         TEXT NOT NULL,
    note          TEXT,
    ts            TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -------------------------------------------------------------- runs
    def has_run(self, model: str, prompt_id: str, run_idx: int) -> bool:
        r = self.db.execute(
            "SELECT 1 FROM runs WHERE model=? AND prompt_id=? AND run_idx=? AND error IS NULL",
            (model, prompt_id, run_idx),
        ).fetchone()
        return r is not None

    def add_run(self, **kw) -> int:
        kw.setdefault("ts", utcnow())
        if isinstance(kw.get("params_json"), dict):
            kw["params_json"] = json.dumps(kw["params_json"], sort_keys=True)
        cols = ",".join(kw)
        q = ",".join("?" for _ in kw)
        upd = ",".join(f"{k}=excluded.{k}" for k in kw if k not in ("model", "prompt_id", "run_idx"))
        cur = self.db.execute(
            f"INSERT INTO runs ({cols}) VALUES ({q}) ON CONFLICT(model, prompt_id, run_idx) DO UPDATE SET {upd} RETURNING id",
            tuple(kw.values()),
        )
        rid = cur.fetchone()[0]
        self.db.commit()
        return rid

    def total_cost(self, model: str | None = None) -> float:
        if model:
            r = self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM runs WHERE model=?", (model,)).fetchone()
        else:
            r = self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM runs").fetchone()
        return float(r[0])

    # ------------------------------------------------------- extractions
    def replace_extractions(self, run_id: int, extractions) -> None:
        self.db.execute("DELETE FROM verdicts WHERE extraction_id IN (SELECT id FROM extractions WHERE run_id=?)", (run_id,))
        self.db.execute("DELETE FROM extractions WHERE run_id=?", (run_id,))
        self.db.executemany(
            "INSERT INTO extractions (run_id, ecosystem, name_raw, name_norm, surface_form, resolution, context) VALUES (?,?,?,?,?,?,?)",
            [(run_id, e.ecosystem, e.name_raw, e.name_norm, e.surface_form, e.resolution, e.context) for e in extractions],
        )
        self.db.commit()

    # ------------------------------------------------------------ oracle
    def get_oracle(self, ecosystem: str, name_norm: str):
        return self.db.execute("SELECT * FROM oracle WHERE ecosystem=? AND name_norm=?", (ecosystem, name_norm)).fetchone()

    def put_oracle(self, row: dict) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO oracle
               (ecosystem, name_norm, bucket, exists_, first_release, last_release, downloads_30d, latest_version, summary, checked_at)
               VALUES (:ecosystem, :name_norm, :bucket, :exists_, :first_release, :last_release, :downloads_30d, :latest_version, :summary, :checked_at)""",
            row,
        )
        self.db.commit()

    def log_lookup(self, ecosystem: str, name_norm: str, url: str, status, latency_ms: float, error: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO lookups (ts, ecosystem, name_norm, url, status, latency_ms, error) VALUES (?,?,?,?,?,?,?)",
            (utcnow(), ecosystem, name_norm, url, status, latency_ms, error),
        )
        self.db.commit()

    def label(self, label: str, *, extraction_id=None, ecosystem=None, name_norm=None, note=None) -> None:
        self.db.execute(
            "INSERT INTO labels (extraction_id, ecosystem, name_norm, label, note, ts) VALUES (?,?,?,?,?,?)",
            (extraction_id, ecosystem, name_norm, label, note, utcnow()),
        )
        self.db.commit()

    def misattributed(self) -> set[tuple[str, str]]:
        rows = self.db.execute("SELECT ecosystem, name_norm FROM labels WHERE label='misattributed' AND name_norm IS NOT NULL")
        return {(r[0], r[1]) for r in rows}
