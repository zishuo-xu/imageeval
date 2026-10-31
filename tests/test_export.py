import json

from imageeval.export import export_dataset
from imageeval.models import ReviewSubmit
from imageeval.review import submit_review
from imageeval.runs import create_run
from tests.test_report import _add_eval


def _seed(db, cfg, rubric, seed_batch):
    batch_id, sample_ids = seed_batch(3)
    run_id = create_run(db, cfg, rubric, batch_id, "export")
    eval_ids = [
        _add_eval(db, run_id, sample_ids[0], (4, 4, 4)),
        _add_eval(db, run_id, sample_ids[1], (2, 2, 2)),
        _add_eval(db, run_id, sample_ids[2], (5, 5, 5)),
    ]
    submit_review(db, cfg, rubric, eval_ids[0], ReviewSubmit(decision="accepted"))
    submit_review(
        db,
        cfg,
        rubric,
        eval_ids[1],
        ReviewSubmit(
            decision="corrected",
            human_adherence=1,
            human_quality=2,
            human_aesthetics=2,
            reasons={"adherence": "主体缺失"},
        ),
    )
    return run_id


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_export_raw_contains_gold_and_silver(db, cfg, rubric, seed_batch) -> None:
    run_id = _seed(db, cfg, rubric, seed_batch)
    out = export_dataset(db, cfg, run_id, "raw")

    rows = _read(out / "dataset.jsonl")
    assert len(rows) == 3
    qualities = sorted(row["final"]["label_quality"] for row in rows)
    assert qualities == ["gold", "gold", "silver"]
    assert (out / "manifest.json").exists()
    assert len(list((out / "images").iterdir())) == 3
    human_rows = [row["human"] for row in rows if row["human"]]
    assert all("reasons" in human for human in human_rows)
    assert {"adherence": "主体缺失"} in [human["reasons"] for human in human_rows]


def test_export_sft_only_gold(db, cfg, rubric, seed_batch) -> None:
    run_id = _seed(db, cfg, rubric, seed_batch)
    out = export_dataset(db, cfg, run_id, "sft")

    rows = _read(out / "dataset.jsonl")
    assert len(rows) == 2
    assert all(row["label_quality"] == "gold" for row in rows)
    assert set(rows[0]["label"]) == {"adherence", "quality", "aesthetics", "overall"}


def test_export_only_reviewed(db, cfg, rubric, seed_batch) -> None:
    run_id = _seed(db, cfg, rubric, seed_batch)
    out = export_dataset(db, cfg, run_id, "only-reviewed")
    rows = _read(out / "dataset.jsonl")
    assert len(rows) == 2
    assert all(row["final"]["source"] == "human" for row in rows)


def test_export_rejects_unknown_mode(db, cfg, rubric, seed_batch) -> None:
    run_id = _seed(db, cfg, rubric, seed_batch)
    try:
        export_dataset(db, cfg, run_id, "bad")
    except ValueError as exc:
        assert "unknown mode" in str(exc)
    else:
        raise AssertionError("expected ValueError")
