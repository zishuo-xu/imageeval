from __future__ import annotations

import json
import uuid

from .config import AppConfig
from .db import Database
from .models import ReviewSubmit
from .rubric.loader import Rubric
from .scoring import compute_overall
from .util import round_half_up, utcnow

QUEUE_FILTERS = {
    "pending": "st.state = 'ai_done'",
    "reviewed": "st.state IN ('accepted', 'corrected')",
    "skipped": "st.state = 'skipped'",
    "error": "st.state = 'error'",
    "all": "1 = 1",
}

QUEUE_ORDERS = {
    "default": "s.created_at ASC",
    "low_ai": "e.overall_score IS NULL, e.overall_score ASC",
    "max_correction": "correction DESC",
    "random": "RANDOM()",
}

_BASE_FROM = """
FROM runs rn
JOIN samples s ON s.batch_id = rn.batch_id
JOIN evaluations e ON e.sample_id = s.id AND e.run_id = rn.id
JOIN v_evaluation_state st ON st.id = e.id
LEFT JOIN reviews r ON r.id = (
    SELECT id FROM reviews WHERE evaluation_id = e.id
    ORDER BY created_at DESC, id DESC LIMIT 1
)
"""

_SELECT = """
SELECT s.id AS sample_id, s.query_text, s.image_path, s.thumb_path, s.model_name, s.tags_json,
       e.id AS evaluation_id, e.status AS eval_status,
       e.adherence_score, e.quality_score, e.aesthetics_score, e.overall_score,
       e.requirements_json, e.subscores_json, e.observation, e.verdict,
       e.error, e.parse_attempts,
       st.state,
       r.id AS review_id, r.decision, r.human_adherence, r.human_quality,
       r.human_aesthetics, r.human_overall, r.note AS review_note,
       r.reasons_json, r.created_at AS reviewed_at,
       (COALESCE(ABS(r.human_adherence - e.adherence_score), 0)
        + COALESCE(ABS(r.human_quality - e.quality_score), 0)
        + COALESCE(ABS(r.human_aesthetics - e.aesthetics_score), 0)) AS correction
"""


def _row_to_item(row) -> dict:
    human = None
    if row["review_id"] is not None:
        human = {
            "decision": row["decision"],
            "adherence": row["human_adherence"],
            "quality": row["human_quality"],
            "aesthetics": row["human_aesthetics"],
            "overall": row["human_overall"],
            "reasons": json.loads(row["reasons_json"] or "{}"),
            "note": row["review_note"] or "",
            "reviewed_at": row["reviewed_at"],
        }
    return {
        "sample_id": row["sample_id"],
        "evaluation_id": row["evaluation_id"],
        "eval_status": row["eval_status"],
        "state": row["state"],
        "query": row["query_text"],
        "image_url": f"/api/samples/{row['sample_id']}/image?size=orig",
        "thumb_url": f"/api/samples/{row['sample_id']}/image?size=thumb",
        "model_name": row["model_name"],
        "tags": json.loads(row["tags_json"] or "[]"),
        "ai": {
            "adherence": row["adherence_score"],
            "quality": row["quality_score"],
            "aesthetics": row["aesthetics_score"],
            "overall": row["overall_score"],
            "requirements": json.loads(row["requirements_json"] or "[]"),
            "subscores": json.loads(row["subscores_json"] or "{}"),
            "observation": row["observation"],
            "verdict": row["verdict"],
            "error": row["error"],
            "parse_attempts": row["parse_attempts"],
        },
        "human": human,
    }


def review_queue(
    db: Database,
    run_id: str,
    filter_name: str = "pending",
    order: str = "default",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if filter_name not in QUEUE_FILTERS:
        raise ValueError(f"unknown filter: {filter_name}")
    if order not in QUEUE_ORDERS:
        raise ValueError(f"unknown order: {order}")

    where = f"WHERE rn.id = ? AND {QUEUE_FILTERS[filter_name]}"
    total = db.query_one(f"SELECT COUNT(*) AS c {_BASE_FROM} {where}", (run_id,))["c"]
    rows = db.query(
        f"{_SELECT} {_BASE_FROM} {where} ORDER BY {QUEUE_ORDERS[order]} LIMIT ? OFFSET ?",
        (run_id, limit, offset),
    )
    return {"total": total, "items": [_row_to_item(row) for row in rows]}


def submit_review(
    db: Database,
    cfg: AppConfig,
    rubric: Rubric,
    evaluation_id: str,
    payload: ReviewSubmit,
    reviewer: str | None = None,
) -> dict:
    row = db.query_one("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,))
    if row is None:
        raise LookupError(f"evaluation not found: {evaluation_id}")
    if row["status"] != "ok":
        raise ValueError("cannot review a failed evaluation")

    adherence = quality = aesthetics = None
    if payload.decision == "accepted":
        adherence = payload.human_adherence or round_half_up(row["adherence_score"])
        quality = payload.human_quality or round_half_up(row["quality_score"])
        aesthetics = payload.human_aesthetics or round_half_up(row["aesthetics_score"])
    elif payload.decision == "corrected":
        adherence = payload.human_adherence
        quality = payload.human_quality
        aesthetics = payload.human_aesthetics

    overall = (
        compute_overall(adherence, quality, aesthetics, rubric)
        if adherence is not None
        else None
    )
    review_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO reviews (id, evaluation_id, reviewer, decision, human_adherence, "
        "human_quality, human_aesthetics, human_overall, reasons_json, note, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            review_id,
            evaluation_id,
            reviewer or cfg.reviewer_name,
            payload.decision,
            adherence,
            quality,
            aesthetics,
            overall,
            json.dumps(payload.reasons, ensure_ascii=False),
            payload.note,
            payload.duration_ms,
            utcnow(),
        ),
    )
    return {
        "review_id": review_id,
        "decision": payload.decision,
        "human_adherence": adherence,
        "human_quality": quality,
        "human_aesthetics": aesthetics,
        "human_overall": overall,
    }


def counts(db: Database, run_id: str) -> dict:
    rows = db.query(
        "SELECT st.state AS state, COUNT(*) AS c FROM evaluations e "
        "JOIN v_evaluation_state st ON st.id = e.id WHERE e.run_id = ? GROUP BY st.state",
        (run_id,),
    )
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM samples s JOIN runs r ON r.batch_id = s.batch_id "
        "WHERE r.id = ?",
        (run_id,),
    )["c"]
    return {"total": total, "by_state": {row["state"]: row["c"] for row in rows}}
