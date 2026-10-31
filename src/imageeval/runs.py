from __future__ import annotations

import json
import uuid

from .config import AppConfig
from .db import Database
from .judge.prompts import prompt_hash
from .rubric.loader import Rubric
from .util import utcnow


def create_run(
    db: Database, cfg: AppConfig, rubric: Rubric, batch_id: str, name: str
) -> str:
    batch = db.query_one("SELECT id FROM import_batches WHERE id = ?", (batch_id,))
    if batch is None:
        raise ValueError(f"batch not found: {batch_id}")
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM samples WHERE batch_id = ?", (batch_id,)
    )["c"]
    run_id = str(uuid.uuid4())
    params = {
        "temperature": cfg.judge.temperature,
        "image_max_edge": cfg.judge.image_max_edge,
        "max_concurrency": cfg.pipeline.max_concurrency,
        "rpm": cfg.pipeline.rpm,
        "max_retries": cfg.pipeline.max_retries,
    }
    db.execute(
        "INSERT INTO runs (id, name, batch_id, rubric_version, prompt_hash, provider, "
        "judge_model, params_json, status, total, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (
            run_id,
            name,
            batch_id,
            rubric.version,
            prompt_hash(rubric),
            cfg.judge.provider,
            cfg.judge.model,
            json.dumps(params, ensure_ascii=False),
            total,
            utcnow(),
        ),
    )
    return run_id


def get_run(db: Database, run_id: str) -> dict:
    row = db.query_one(
        "SELECT r.*, b.source_name FROM runs r "
        "JOIN import_batches b ON b.id = r.batch_id WHERE r.id = ?",
        (run_id,),
    )
    if row is None:
        raise LookupError(f"run not found: {run_id}")
    return dict(row)


def list_runs(db: Database, batch_id: str | None = None) -> list[dict]:
    if batch_id:
        rows = db.query(
            "SELECT * FROM runs WHERE batch_id = ? ORDER BY created_at DESC", (batch_id,)
        )
    else:
        rows = db.query("SELECT * FROM runs ORDER BY created_at DESC")
    return [dict(row) for row in rows]
