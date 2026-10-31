from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .db import Database
from .storage import resolve_under

MODES = ("raw", "sft", "only-reviewed")


def _reviewed(decision: str | None) -> bool:
    return decision in ("accepted", "corrected")


def export_dataset(db: Database, cfg: AppConfig, run_id: str, mode: str) -> Path:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")

    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise LookupError(f"run not found: {run_id}")

    rows = db.query(
        "SELECT s.id AS sample_id, s.query_text, s.image_path, s.model_name, s.tags_json, "
        "e.adherence_score, e.quality_score, e.aesthetics_score, e.overall_score, "
        "e.requirements_json, e.subscores_json, e.verdict, "
        "r.decision, r.human_adherence, r.human_quality, r.human_aesthetics, r.human_overall, "
        "r.note, r.reviewer, r.duration_ms AS review_duration_ms "
        "FROM samples s "
        "JOIN runs rn ON rn.batch_id = s.batch_id AND rn.id = ? "
        "JOIN evaluations e ON e.sample_id = s.id AND e.run_id = rn.id AND e.status = 'ok' "
        "LEFT JOIN reviews r ON r.id = ("
        "  SELECT id FROM reviews WHERE evaluation_id = e.id ORDER BY created_at DESC, id DESC LIMIT 1"
        ") "
        "ORDER BY s.created_at",
        (run_id,),
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = cfg.exports_dir / f"{run_id}_{mode}_{stamp}"
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    manifest_images: list[str] = []
    gold = 0
    silver = 0

    for row in rows:
        reviewed = _reviewed(row["decision"])
        if mode in ("sft", "only-reviewed") and not reviewed:
            continue

        source = resolve_under(cfg.images_dir, row["image_path"])
        suffix = source.suffix.lower() or ".png"
        image_rel = f"images/{row['sample_id']}{suffix}"
        shutil.copy2(source, out_dir / image_rel)
        manifest_images.append(image_rel)

        ai_scores = {
            "adherence": row["adherence_score"],
            "quality": row["quality_score"],
            "aesthetics": row["aesthetics_score"],
            "overall": row["overall_score"],
        }
        if reviewed:
            gold += 1
            final_scores = {
                "adherence": row["human_adherence"],
                "quality": row["human_quality"],
                "aesthetics": row["human_aesthetics"],
                "overall": row["human_overall"],
            }
            human = {
                "adherence": row["human_adherence"],
                "quality": row["human_quality"],
                "aesthetics": row["human_aesthetics"],
                "overall": row["human_overall"],
                "note": row["note"] or "",
                "reviewer": row["reviewer"],
                "decision": row["decision"],
            }
            label_quality = "gold"
            final_source = "human"
        else:
            silver += 1
            final_scores = dict(ai_scores)
            human = None
            label_quality = "silver"
            final_source = "ai"

        if mode == "sft":
            records.append(
                {
                    "image": image_rel,
                    "query": row["query_text"],
                    "label": final_scores,
                    "label_quality": label_quality,
                    "meta": {
                        "sample_id": row["sample_id"],
                        "rubric_version": run["rubric_version"],
                        "reviewer": row["reviewer"],
                        "model_name": row["model_name"],
                    },
                }
            )
            continue

        records.append(
            {
                "sample_id": row["sample_id"],
                "query": row["query_text"],
                "image": image_rel,
                "model_name": row["model_name"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "rubric_version": run["rubric_version"],
                "prompt_hash": run["prompt_hash"],
                "judge": {"provider": run["provider"], "model": run["judge_model"]},
                "ai": {
                    **ai_scores,
                    "requirements": json.loads(row["requirements_json"] or "[]"),
                    "subscores": json.loads(row["subscores_json"] or "{}"),
                    "verdict": row["verdict"],
                },
                "human": human,
                "final": {
                    "scores": final_scores,
                    "source": final_source,
                    "label_quality": label_quality,
                },
                "meta": {
                    "created_at": run["created_at"],
                    "review_duration_ms": row["review_duration_ms"],
                },
            }
        )

    with (out_dir / "dataset.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "run_id": run_id,
        "mode": mode,
        "rubric_version": run["rubric_version"],
        "prompt_hash": run["prompt_hash"],
        "judge": {"provider": run["provider"], "model": run["judge_model"]},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"total": len(records), "gold": gold, "silver": silver},
        "images": manifest_images,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir
