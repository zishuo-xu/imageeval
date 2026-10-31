import asyncio

from imageeval.judge.fake import FakeProvider
from imageeval.pipeline import execute_run
from imageeval.runs import create_run


def _run(db, cfg, rubric, batch_id: str, provider: FakeProvider) -> str:
    run_id = create_run(db, cfg, rubric, batch_id, "test run")
    asyncio.run(execute_run(db, cfg, provider, rubric, run_id))
    return run_id


def test_execute_run_scores_all_and_retries(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(2)
    provider = FakeProvider(fail_times=1)

    run_id = _run(db, cfg, rubric, batch_id, provider)

    rows = db.query("SELECT * FROM evaluations WHERE run_id = ?", (run_id,))
    assert len(rows) == 2
    assert all(row["status"] == "ok" for row in rows)
    assert all(row["adherence_score"] is not None for row in rows)
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["status"] == "completed"
    assert run["done"] == 2
    assert run["failed"] == 0
    assert provider.calls == 3


def test_execute_run_resume_skips_completed(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(2)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider())

    provider = FakeProvider()
    asyncio.run(execute_run(db, cfg, provider, rubric, run_id))
    assert provider.calls == 0
    assert db.query_one("SELECT done FROM runs WHERE id = ?", (run_id,))["done"] == 2


def test_execute_run_marks_error_after_retries(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(1)
    provider = FakeProvider(fail_times=10)

    run_id = _run(db, cfg, rubric, batch_id, provider)

    row = db.query_one("SELECT * FROM evaluations WHERE run_id = ?", (run_id,))
    assert row["status"] == "error"
    assert "fake transient failure" in row["error"]
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["failed"] == 1
    assert run["status"] == "completed"


def test_create_run_validates_batch(db, cfg, rubric) -> None:
    try:
        create_run(db, cfg, rubric, "missing", "x")
    except ValueError as exc:
        assert "batch not found" in str(exc)
    else:
        raise AssertionError("expected ValueError")
