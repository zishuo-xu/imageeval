from __future__ import annotations

import base64
import copy
import html
import json
import math
from pathlib import Path

from .db import Database
from .review import counts
from .rubric.loader import Rubric
from .storage import resolve_under

DIMENSIONS = ("adherence", "quality", "aesthetics")

WEB_DIR = Path(__file__).parent / "web"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return numerator / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    value = _pearson(_rank(xs), _rank(ys))
    return round(value, 3) if value is not None else None


def _mae(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return round(sum(abs(a - b) for a, b in pairs) / len(pairs), 3)


def _hist(values: list[float]) -> list[int]:
    bins = [0, 0, 0, 0, 0]
    for value in values:
        index = min(4, max(0, int(round(value)) - 1))
        bins[index] += 1
    return bins


def _latest_reviews(db: Database, run_id: str) -> list:
    return db.query(
        "SELECT s.id AS sample_id, s.query_text, s.image_path, s.thumb_path, "
        "e.id AS evaluation_id, e.adherence_score, e.quality_score, e.aesthetics_score, "
        "e.overall_score, e.requirements_json, e.verdict, "
        "r.human_adherence, r.human_quality, r.human_aesthetics, r.human_overall, r.decision "
        "FROM evaluations e "
        "JOIN samples s ON s.id = e.sample_id "
        "JOIN reviews r ON r.id = ("
        "  SELECT id FROM reviews WHERE evaluation_id = e.id ORDER BY created_at DESC, id DESC LIMIT 1"
        ") "
        "WHERE e.run_id = ? AND e.status = 'ok'",
        (run_id,),
    )


def select_failure_cases(rows: list[dict], top_n: int = 12) -> list[dict]:
    candidates: list[tuple[float, float, dict]] = []
    for row in rows:
        human_overall = row.get("human_overall")
        if human_overall is None:
            continue
        correction = float(row.get("correction", 0.0) or 0.0)
        if human_overall <= 3.0 or correction >= 1.5:
            candidates.append((float(human_overall), -correction, row))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in candidates[:top_n]]


def build_summary(db: Database, run_id: str, rubric: Rubric) -> dict:
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise LookupError(f"run not found: {run_id}")

    ai_rows = db.query(
        "SELECT * FROM evaluations WHERE run_id = ? AND status = 'ok' ORDER BY created_at",
        (run_id,),
    )
    reviewed = _latest_reviews(db, run_id)
    scored = [row for row in reviewed if row["decision"] in ("accepted", "corrected")]

    run_counts = counts(db, run_id)
    state_counts = run_counts["by_state"]
    summary_counts = {
        "total": run_counts["total"],
        "ok": len(ai_rows),
        "error": state_counts.get("error", 0),
        "ai_done": state_counts.get("ai_done", 0),
        "accepted": state_counts.get("accepted", 0),
        "corrected": state_counts.get("corrected", 0),
        "skipped": state_counts.get("skipped", 0),
        "reviewed": state_counts.get("accepted", 0) + state_counts.get("corrected", 0),
    }

    ai_values = {
        dim: [row[f"{dim}_score"] for row in ai_rows if row[f"{dim}_score"] is not None]
        for dim in DIMENSIONS
    }
    human_values = {
        dim: [row[f"human_{dim}"] for row in scored if row[f"human_{dim}"] is not None]
        for dim in DIMENSIONS
    }

    agreement = {}
    confusion = {}
    scatter = []
    for dim in DIMENSIONS:
        pairs = [
            (row[f"{dim}_score"], row[f"human_{dim}"])
            for row in scored
            if row[f"{dim}_score"] is not None and row[f"human_{dim}"] is not None
        ]
        agreement[dim] = {
            "mae": _mae(pairs),
            "spearman": spearman([a for a, _ in pairs], [b for _, b in pairs]),
        }
        matrix = [[0] * 5 for _ in range(5)]
        for ai_value, human_value in pairs:
            matrix[min(4, max(0, int(round(ai_value)) - 1))][min(4, max(0, human_value - 1))] += 1
        confusion[dim] = matrix
        scatter.extend(
            {"dim": dim, "ai": round(ai_value, 2), "human": human_value}
            for ai_value, human_value in pairs
        )

    status_counts = {"satisfied": 0, "partial": 0, "missing": 0, "contradicted": 0}
    by_category: dict[str, dict[str, int]] = {}
    for row in ai_rows:
        for requirement in json.loads(row["requirements_json"] or "[]"):
            status = requirement.get("status", "missing")
            status_counts[status] = status_counts.get(status, 0) + 1
            category = requirement.get("category", "unknown")
            bucket = by_category.setdefault(category, {"total": 0, "failed": 0})
            bucket["total"] += 1
            if status != "satisfied":
                bucket["failed"] += 1

    category_rows = [
        {
            "category": category,
            "total": bucket["total"],
            "failed": bucket["failed"],
            "failure_rate": round(bucket["failed"] / bucket["total"], 3)
            if bucket["total"]
            else 0.0,
        }
        for category, bucket in by_category.items()
    ]
    category_rows.sort(key=lambda row: (-row["failure_rate"], -row["total"]))

    reviewed_samples = []
    for row in scored[:200]:
        reviewed_samples.append(
            {
                "sample_id": row["sample_id"],
                "query": row["query_text"],
                "ai": {
                    "adherence": row["adherence_score"],
                    "quality": row["quality_score"],
                    "aesthetics": row["aesthetics_score"],
                    "overall": row["overall_score"],
                },
                "human": {
                    "adherence": row["human_adherence"],
                    "quality": row["human_quality"],
                    "aesthetics": row["human_aesthetics"],
                    "overall": row["human_overall"],
                },
            }
        )

    failure_rows = []
    for row in scored:
        correction = sum(
            abs(row[f"{dim}_score"] - row[f"human_{dim}"])
            for dim in DIMENSIONS
            if row[f"{dim}_score"] is not None and row[f"human_{dim}"] is not None
        )
        failure_rows.append(
            {
                "sample_id": row["sample_id"],
                "query": row["query_text"],
                "thumb_path": row["thumb_path"],
                "image_path": row["image_path"],
                "ai_adherence": row["adherence_score"],
                "ai_quality": row["quality_score"],
                "ai_aesthetics": row["aesthetics_score"],
                "ai_overall": row["overall_score"],
                "human_adherence": row["human_adherence"],
                "human_quality": row["human_quality"],
                "human_aesthetics": row["human_aesthetics"],
                "human_overall": row["human_overall"],
                "correction": round(correction, 2),
                "requirements": json.loads(row["requirements_json"] or "[]"),
                "verdict": row["verdict"],
            }
        )

    accepted = state_counts.get("accepted", 0)
    corrected = state_counts.get("corrected", 0)
    acceptance_rate = round(accepted / (accepted + corrected), 3) if (accepted + corrected) else None

    return {
        "run": dict(run),
        "counts": summary_counts,
        "means": {
            "ai": {dim: _mean(ai_values[dim]) for dim in DIMENSIONS},
            "human": {dim: _mean(human_values[dim]) for dim in DIMENSIONS},
        },
        "acceptance_rate": acceptance_rate,
        "distributions": {
            dim: {"ai": _hist(ai_values[dim]), "human": _hist(human_values[dim])}
            for dim in DIMENSIONS
        },
        "radar": {
            "labels": ["需求遵循", "视觉质量", "美学"],
            "ai": [_mean(ai_values[dim]) for dim in DIMENSIONS],
            "human": [_mean(human_values[dim]) for dim in DIMENSIONS],
        },
        "agreement": {
            "n": len(scored),
            "mae": {dim: agreement[dim]["mae"] for dim in DIMENSIONS},
            "spearman": {dim: agreement[dim]["spearman"] for dim in DIMENSIONS},
            "confusion": confusion,
            "scatter": scatter,
        },
        "attribution": {
            "status_counts": status_counts,
            "by_category": category_rows,
        },
        "failures": select_failure_cases(failure_rows),
        "samples": reviewed_samples,
    }


def _inline_image(thumb_path: str, data_dir: Path) -> str:
    if not thumb_path:
        return ""
    path = resolve_under(data_dir / "thumbs", thumb_path)
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def render_report_html(summary: dict, data_dir: Path, inline_images: bool = False) -> str:
    data = copy.deepcopy(summary)
    for case in data.get("failures", []):
        if inline_images:
            case["image"] = _inline_image(case.get("thumb_path", ""), data_dir)
        else:
            case["image"] = f"/api/samples/{case['sample_id']}/image?size=thumb"

    template = (WEB_DIR / "report.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    chart_js = (WEB_DIR / "vendor" / "chart.umd.js").read_text(encoding="utf-8")
    report_js = (WEB_DIR / "report.js").read_text(encoding="utf-8")
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = f"评测报告 · {html.escape(str(data.get('run', {}).get('name', '')))}"

    return (
        template.replace("{{TITLE}}", title)
        .replace("{{CSS}}", css)
        .replace("{{CHART_JS}}", chart_js)
        .replace("{{DATA_JSON}}", data_json)
        .replace("{{REPORT_JS}}", report_js)
    )
