import json
import uuid

import pytest

from imageeval.report import build_summary, select_failure_cases, spearman
from imageeval.review import submit_review
from imageeval.models import ReviewSubmit
from imageeval.runs import create_run


def _add_eval(db, run_id, sample_id, scores, requirements=None) -> str:
    evaluation_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, adherence_score, quality_score, "
        "aesthetics_score, overall_score, requirements_json, subscores_json, observation, verdict, "
        "raw_response, created_at) VALUES (?, ?, ?, 'ok', ?, ?, ?, ?, ?, '{}', 'o', 'v', 'raw', 'now')",
        (
            evaluation_id,
            sample_id,
            run_id,
            scores[0],
            scores[1],
            scores[2],
            round(0.4 * scores[0] + 0.35 * scores[1] + 0.25 * scores[2], 2),
            json.dumps(
                requirements
                or [
                    {
                        "text": "主体",
                        "category": "subject",
                        "criticality": "critical",
                        "status": "satisfied",
                        "evidence": "e",
                    }
                ]
            ),
        ),
    )
    return evaluation_id


def _seed(db, cfg, rubric, seed_batch, scores_list, requirements=None):
    batch_id, sample_ids = seed_batch(len(scores_list))
    run_id = create_run(db, cfg, rubric, batch_id, "report")
    eval_ids = [
        _add_eval(db, run_id, sample_id, scores, requirements)
        for sample_id, scores in zip(sample_ids, scores_list)
    ]
    return run_id, sample_ids, eval_ids


def test_build_summary_means_and_agreement(db, cfg, rubric, seed_batch) -> None:
    run_id, sample_ids, eval_ids = _seed(
        db, cfg, rubric, seed_batch, [(4, 4, 4), (2, 2, 2), (3, 4, 4)]
    )
    submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    submit_review(
        db,
        cfg,
        rubric,
        eval_ids[1],
        ReviewSubmit(decision="corrected", human_adherence=2, human_quality=2, human_aesthetics=2),
    )

    summary = build_summary(db, run_id, rubric)

    assert summary["counts"]["total"] == 3
    assert summary["counts"]["accepted"] == 1
    assert summary["counts"]["corrected"] == 1
    assert summary["counts"]["ai_done"] == 1
    assert summary["means"]["ai"]["adherence"] == pytest.approx(3.0)
    assert summary["means"]["human"]["adherence"] == pytest.approx(3.0)
    assert summary["acceptance_rate"] == pytest.approx(0.5)
    assert summary["agreement"]["n"] == 2
    assert summary["agreement"]["mae"]["adherence"] == pytest.approx(0.0)


def test_requirement_attribution(db, cfg, rubric, seed_batch) -> None:
    requirements = [
        {
            "text": "主体",
            "category": "subject",
            "criticality": "critical",
            "status": "satisfied",
            "evidence": "e",
        },
        {
            "text": "数量",
            "category": "count",
            "criticality": "normal",
            "status": "missing",
            "evidence": "只画了一只",
        },
    ]
    run_id, _, _ = _seed(db, cfg, rubric, seed_batch, [(3, 3, 3)], requirements=requirements)

    summary = build_summary(db, run_id, rubric)

    attribution = summary["attribution"]
    assert attribution["status_counts"]["satisfied"] == 1
    assert attribution["status_counts"]["missing"] == 1
    count_row = next(row for row in attribution["by_category"] if row["category"] == "count")
    assert count_row["failed"] == 1
    assert count_row["failure_rate"] == pytest.approx(1.0)


def test_failure_selection_default_policy(db, cfg, rubric, seed_batch) -> None:
    run_id, _, eval_ids = _seed(
        db, cfg, rubric, seed_batch, [(4, 4, 4), (2, 3, 2), (5, 5, 5)]
    )
    submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    submit_review(
        db,
        cfg,
        rubric,
        eval_ids[1],
        ReviewSubmit(decision="corrected", human_adherence=1, human_quality=2, human_aesthetics=2),
    )
    submit_review(db, cfg, rubric, eval_ids[2], ReviewSubmit(decision="accepted"))

    summary = build_summary(db, run_id, rubric)
    failures = summary["failures"]

    assert len(failures) == 1
    assert failures[0]["human_overall"] == pytest.approx(1.6)


def test_select_failure_cases_thresholds() -> None:
    rows = [
        {"sample_id": "a", "human_overall": 4.0, "correction": 0.0},
        {"sample_id": "b", "human_overall": 4.5, "correction": 2.0},
        {"sample_id": "c", "human_overall": 2.0, "correction": 0.5},
        {"sample_id": "d", "human_overall": 3.5, "correction": 0.2},
    ]
    selected = select_failure_cases(rows, top_n=10)
    assert [row["sample_id"] for row in selected] == ["c", "b"]


def test_spearman() -> None:
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None
