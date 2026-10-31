from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    report_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS samples (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    image_path TEXT NOT NULL,
    thumb_path TEXT,
    ref_image_path TEXT,
    model_name TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, external_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES import_batches(id),
    rubric_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    adherence_score REAL,
    quality_score REAL,
    aesthetics_score REAL,
    overall_score REAL,
    requirements_json TEXT NOT NULL DEFAULT '[]',
    subscores_json TEXT NOT NULL DEFAULT '{}',
    observation TEXT,
    verdict TEXT,
    raw_response TEXT,
    parse_attempts INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    latency_ms INTEGER,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(sample_id, run_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    human_adherence INTEGER,
    human_quality INTEGER,
    human_aesthetics INTEGER,
    human_overall REAL,
    reasons_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_batch ON samples(batch_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_run ON evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_reviews_evaluation ON reviews(evaluation_id);

CREATE VIEW IF NOT EXISTS v_evaluation_state AS
SELECT
    e.*,
    CASE
        WHEN e.status = 'error' THEN 'error'
        WHEN lr.id IS NULL THEN 'ai_done'
        ELSE lr.decision
    END AS state
FROM evaluations e
LEFT JOIN (
    SELECT r.*, ROW_NUMBER() OVER (
        PARTITION BY r.evaluation_id ORDER BY r.created_at DESC, r.id DESC
    ) AS rn
    FROM reviews r
) lr ON lr.evaluation_id = e.id AND lr.rn = 1;
"""

MIGRATIONS: dict[int, str] = {1: SCHEMA_V1}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        current = 0
    else:
        current = int(row["version"] if isinstance(row, sqlite3.Row) else row[0])

    for version in sorted(MIGRATIONS):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            conn.execute("UPDATE schema_version SET version = ?", (version,))
            conn.commit()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._tx_depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            if self._tx_depth == 0:
                self._conn.commit()
            return cursor

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            if self._tx_depth == 0:
                self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._tx_depth += 1
            try:
                yield self._conn
            except BaseException:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._conn.rollback()
                raise
            else:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def mark_stale_runs(db: Database) -> None:
    db.execute("UPDATE runs SET status = 'paused' WHERE status = 'running'")
