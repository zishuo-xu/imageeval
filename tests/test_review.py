import json
import uuid

import pytest

from imageeval.models import ReviewSubmit
from imageeval.review import counts, review_queue, submit_review
from imageeval.runs import create_run


def _add_eval(db, run_id: str, sample_id: str, score: float = 4.0) -> str:
    evaluation_id = str(uuid.uuid4())
    requirements = [
        {
            "text": "主体",
            "category": "subject",
            "criticality": "critical",
            "status": "satisfied",
            "evidence": "e",
        }
    ]
    subscores = {
        "quality": {"clarity": {"score": 4, "reason": "r"}},
        "aesthetics": {"composition": {"score": 4, "reason": "r"}},
    }
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, adherence_score, quality_score, "
        "aesthetics_score, overall_score, requirements_json, subscores_json, observation, verdict, "
        "raw_response, created_at) VALUES (?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, 'o', 'v', 'raw', 'now')",
        (
            evaluation_id,
            sample_id,
            run_id,
            score,
            score,
            score,
            score,
            json.dumps(requirements),
            json.dumps(subscores),
        ),
    )
    return evaluation_id


def _seed_run(db, cfg, rubric, seed_batch):
    batch_id, sample_ids = seed_batch(2)
    run_id = create_run(db, cfg, rubric, batch_id, "r")
    eval_ids = [_add_eval(db, run_id, sample_id) for sample_id in sample_ids]
    return run_id, sample_ids, eval_ids


def test_review_queue_pending_and_states(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)

    pending = review_queue(db, run_id, "pending")
    assert pending["total"] == 2
    assert {item["state"] for item in pending["items"]} == {"ai_done"}

    submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    pending = review_queue(db, run_id, "pending")
    assert pending["total"] == 1
    assert counts(db, run_id)["by_state"] == {"accepted": 1, "ai_done": 1}


def test_accepted_fills_ai_scores(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)
    result = submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    assert result["human_adherence"] == 4
    assert result["human_overall"] == pytest.approx(4.0)


def test_accepted_rounds_ai_scores_half_up(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)
    db.execute(
        "UPDATE evaluations SET adherence_score = 4.5 WHERE id = ?", (eval_ids[0],)
    )
    result = submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    assert result["human_adherence"] == 5


def test_error_filter_exposes_error_details(db, cfg, rubric, seed_batch) -> None:
    run_id, sample_ids, _ = _seed_run(db, cfg, rubric, seed_batch)
    db.execute("DELETE FROM evaluations WHERE sample_id = ?", (sample_ids[0],))
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, error, parse_attempts, created_at) "
        "VALUES (?, ?, ?, 'error', 'schema boom', 2, 'now')",
        (str(uuid.uuid4()), sample_ids[0], run_id),
    )

    queue = review_queue(db, run_id, "error")

    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["state"] == "error"
    assert item["eval_status"] == "error"
    assert item["ai"]["error"] == "schema boom"
    assert item["ai"]["parse_attempts"] == 2


def test_corrected_requires_and_persists_scores(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)
    result = submit_review(
        db,
        cfg,
        rubric,
        eval_ids[0],
        ReviewSubmit(
            decision="corrected",
            human_adherence=2,
            human_quality=3,
            human_aesthetics=4,
            reasons={"adherence": "主体缺失"},
        ),
    )
    assert result["human_adherence"] == 2
    assert result["human_overall"] == pytest.approx(2.85)
    row = db.query_one("SELECT * FROM reviews WHERE evaluation_id = ?", (eval_ids[0],))
    assert json.loads(row["reasons_json"]) == {"adherence": "主体缺失"}


def test_latest_review_wins_and_history_kept(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)
    submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    submit_review(
        db,
        cfg,
        rubric,
        eval_ids[0],
        ReviewSubmit(decision="corrected", human_adherence=1, human_quality=1, human_aesthetics=1),
    )
    assert counts(db, run_id)["by_state"]["corrected"] == 1
    assert db.query_one(
        "SELECT COUNT(*) AS c FROM reviews WHERE evaluation_id = ?", (eval_ids[0],)
    )["c"] == 2


def test_cannot_review_failed_evaluation(db, cfg, rubric, seed_batch) -> None:
    run_id, sample_ids, _ = _seed_run(db, cfg, rubric, seed_batch)
    db.execute("DELETE FROM evaluations WHERE sample_id = ?", (sample_ids[0],))
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, error, created_at) "
        "VALUES (?, ?, ?, 'error', 'boom', 'now')",
        (str(uuid.uuid4()), sample_ids[0], run_id),
    )
    failed_id = db.query_one(
        "SELECT id FROM evaluations WHERE sample_id = ?", (sample_ids[0],)
    )["id"]
    with pytest.raises(ValueError, match="failed evaluation"):
        submit_review(db, cfg, rubric, failed_id, ReviewSubmit(decision="accepted"))


def test_skipped_stores_nulls(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed_run(db, cfg, rubric, seed_batch)

    result = submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="skipped"))

    assert result["decision"] == "skipped"
    assert result["human_adherence"] is None
    assert result["human_overall"] is None
    row = db.query_one("SELECT * FROM reviews WHERE evaluation_id = ?", (eval_ids[0],))
    assert row["human_adherence"] is None
    assert row["human_quality"] is None
    assert row["human_aesthetics"] is None
    assert row["human_overall"] is None
    assert counts(db, run_id)["by_state"]["skipped"] == 1


@pytest.mark.parametrize("order", ["default", "low_ai", "max_correction", "random"])
def test_grid_pagination_has_no_duplicates(db, cfg, rubric, seed_batch, order):
    batch_id, sample_ids = seed_batch(33)
    run_id = create_run(db, cfg, rubric, batch_id, "grid")
    for sample_id in sample_ids:
        _add_eval(db, run_id, sample_id)
    pages = [review_queue(db, run_id, order=order, limit=16, offset=offset) for offset in (0, 16, 32)]
    assert [len(page["items"]) for page in pages] == [16, 16, 1]
    ids = [item["sample_id"] for page in pages for item in page["items"]]
    assert len(set(ids)) == 33
    assert review_queue(db, run_id, order=order, limit=16)["items"] == pages[0]["items"]


@pytest.mark.parametrize("limit,offset", [(0, 0), (201, 0), (16, -1)])
def test_queue_rejects_invalid_page(db, limit, offset):
    with pytest.raises(ValueError):
        review_queue(db, "run", limit=limit, offset=offset)
