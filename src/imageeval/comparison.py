from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .util import utcnow


class ComparisonVote(BaseModel):
    winner: Literal["A", "B", "tie"]
    note: str = Field(default="", max_length=2000)


def list_experiments(manager):
    jobs = [json.loads(path.read_text()) for path in manager.root.glob("*/job.json")]
    return [{"id": j["id"], "name": j["request"]["name"], "status": j["status"], "created_at": j["created_at"],
             "total": j["total"], "generated": j["generated"], "run_id": j["run_id"]}
            for j in sorted(jobs, key=lambda j: j["created_at"], reverse=True) if j["request"].get("ab_compare")]


def get_comparison(manager, db, experiment_id: UUID, run_id: UUID | None = None):
    job = manager.get(experiment_id)
    if run_id:
        selected = db.query_one("SELECT batch_id FROM runs WHERE id=?", (str(run_id),))
        if selected is None or selected["batch_id"] != job["batch_id"]:
            raise LookupError("评分版本不属于此 A/B 图片批次")
        job["run_id"] = str(run_id)
    req = job["request"]
    if not req.get("ab_compare"):
        raise LookupError("此任务不是 A/B 实验")
    pairs = {}
    for index, query in enumerate(req["original_queries"]):
        for candidate in range(req["images_per_prompt"]):
            pair_id = f"{index + 1}-{candidate + 1}"
            pairs[pair_id] = {"id": pair_id, "query": query, "prompt_a": query, "prompt_b": req["prompts"][index],
                              "query_index": index, "candidate_index": candidate, "A": None, "B": None, "vote": None}
    if job["batch_id"]:
        rows = db.query("""SELECT s.id, s.metadata_json, e.status, e.error, e.adherence_score, e.quality_score,
                                  e.aesthetics_score, e.overall_score, e.subscores_json
                           FROM samples s LEFT JOIN evaluations e ON e.sample_id=s.id AND e.run_id=?
                           WHERE s.batch_id=? ORDER BY s.rowid""", (job["run_id"], job["batch_id"]))
        for row in rows:
            meta = json.loads(row["metadata_json"])
            comparison = meta["comparison"]
            pair = pairs[comparison["pair_id"]]
            pair[comparison["variant"]] = {"sample_id": row["id"], "image_url": f"/api/samples/{row['id']}/image?size=orig",
                "thumb_url": f"/api/samples/{row['id']}/image?size=thumb", "status": row["status"] or "pending",
                "feedback": json.loads(row["subscores_json"] or "{}").get("feedback"),
                "error": row["error"], "checks": json.loads(row["subscores_json"] or "{}").get("checks", []), "scores": {key: row[f"{key}_score"] for key in ("adherence", "quality", "aesthetics", "overall")},
                "prompt_expansion": meta.get("prompt_expansion")}
    for row in db.query("SELECT * FROM comparison_votes WHERE experiment_id=?", (str(experiment_id),)):
        pairs[row["pair_id"]]["vote"] = {k: row[k] for k in ("winner", "note", "updated_at")}
    complete = [p for p in pairs.values() if p["A"] and p["B"]]
    scored = [p for p in complete if p["A"]["status"] == p["B"]["status"] == "ok"]
    deltas = {key: round(sum(p["B"]["scores"][key] - p["A"]["scores"][key] for p in scored) / len(scored), 3) if scored else None
              for key in ("adherence", "quality", "aesthetics", "overall")}
    votes = [p["vote"] for p in complete if p["vote"]]
    run = db.query_one("SELECT * FROM runs WHERE id=?", (job["run_id"],)) if job["run_id"] else None
    return {"id": job["id"], "name": req["name"], "status": job["status"], "error": job["error"],
            "generated": job["generated"], "total": job["total"], "run_id": job["run_id"], "run": dict(run) if run else None,
            "model": job["model"], "aspect_ratio": req["aspect_ratio"], "seed_controlled": False,
            "generation_parameters": {"images_per_prompt": req["images_per_prompt"], "aspect_ratio": req["aspect_ratio"], "prompt_optimizer": False},
            "score_runs": [dict(r) for r in db.query("SELECT id,name,status FROM runs WHERE batch_id=? ORDER BY created_at DESC", (job["batch_id"],))],
            "pe_model": job["expansion"]["model"], "pe_template": job["expansion"]["template_version"],
            "pairs": list(pairs.values()),
            "summary": {"pairs": len(pairs), "complete": len(complete), "scored": len(scored), "mean_delta": deltas,
                        "votes": len(votes), "A": sum(v["winner"] == "A" for v in votes),
                        "B": sum(v["winner"] == "B" for v in votes), "tie": sum(v["winner"] == "tie" for v in votes)}}


def save_vote(manager, db, experiment_id, pair_id, vote):
    data = get_comparison(manager, db, experiment_id)
    pair = next((p for p in data["pairs"] if p["id"] == pair_id), None)
    if pair is None:
        raise LookupError("对比样本不存在")
    if not pair["A"] or not pair["B"]:
        raise ValueError("两组图片齐全后才能选优")
    db.execute("""INSERT INTO comparison_votes(experiment_id,pair_id,winner,note,updated_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(experiment_id,pair_id) DO UPDATE SET winner=excluded.winner,note=excluded.note,updated_at=excluded.updated_at""",
               (str(experiment_id), pair_id, vote.winner, vote.note, utcnow()))
    return {"ok": True}
