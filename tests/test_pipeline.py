import asyncio
import json

import pytest

from imageeval.judge.base import SchemaJudgeError
from imageeval.judge.fake import FakeProvider
from imageeval.pipeline import (
    RunManager,
    _save_error,
    execute_run,
    retry_evaluation,
)
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


def test_error_upsert_never_overwrites_ok(db, cfg, rubric, seed_batch) -> None:
    batch_id, sample_ids = seed_batch(1)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider())

    before = db.query_one(
        "SELECT * FROM evaluations WHERE sample_id = ? AND run_id = ?",
        (sample_ids[0], run_id),
    )
    assert before["status"] == "ok"

    _save_error(db, sample_ids[0], run_id, "boom")

    after = db.query_one(
        "SELECT * FROM evaluations WHERE sample_id = ? AND run_id = ?",
        (sample_ids[0], run_id),
    )
    assert after["status"] == "ok"
    assert after["adherence_score"] == before["adherence_score"]
    assert after["quality_score"] == before["quality_score"]
    assert after["aesthetics_score"] == before["aesthetics_score"]
    assert after["overall_score"] == before["overall_score"]
    assert after["error"] is None
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["failed"] == 0


def test_resume_converts_error_to_ok(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(1)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider(fail_times=10))

    failed = db.query_one("SELECT * FROM evaluations WHERE run_id = ?", (run_id,))
    assert failed["status"] == "error"

    asyncio.run(execute_run(db, cfg, FakeProvider(), rubric, run_id))

    rows = db.query("SELECT * FROM evaluations WHERE run_id = ?", (run_id,))
    assert len(rows) == 1
    assert rows[0]["id"] == failed["id"]
    assert rows[0]["status"] == "ok"
    assert rows[0]["error"] is None
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["done"] == 1
    assert run["failed"] == 0
    assert run["status"] == "completed"


class SlowFakeProvider(FakeProvider):
    async def evaluate(self, query, image_path):
        await asyncio.sleep(0.1)
        return await super().evaluate(query, image_path)


class RawSchemaFailProvider:
    name = "schema-fail"
    model = "schema-fail-v1"

    async def evaluate(self, query, image_path):
        raise SchemaJudgeError("invalid judge output after repair: bad", raw="not json", attempts=2)


def test_schema_error_persists_raw_response(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(1)
    run_id = _run(db, cfg, rubric, batch_id, RawSchemaFailProvider())

    row = db.query_one("SELECT * FROM evaluations WHERE run_id = ?", (run_id,))
    assert row["status"] == "error"
    assert "invalid judge output" in row["error"]
    assert row["raw_response"] == "not json"
    assert row["parse_attempts"] == 2
    assert db.query_one("SELECT failed FROM runs WHERE id = ?", (run_id,))["failed"] == 1


def test_retry_evaluation_retries_only_failed_row(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(2)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider(fail_times=10))

    failed = db.query("SELECT id FROM evaluations WHERE run_id = ? ORDER BY created_at", (run_id,))
    assert len(failed) == 2
    target = failed[0]["id"]

    asyncio.run(retry_evaluation(db, cfg, FakeProvider(), rubric, target))

    rows = db.query("SELECT id, status FROM evaluations WHERE run_id = ?", (run_id,))
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[target] == "ok"
    assert sorted(statuses.values()) == ["error", "ok"]
    run = db.query_one("SELECT done, failed FROM runs WHERE id = ?", (run_id,))
    assert run["done"] == 1
    assert run["failed"] == 1


def test_retry_evaluation_refreshes_usage_and_settles_failed_run(
    db, cfg, rubric, seed_batch
) -> None:
    batch_id, _ = seed_batch(1)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider(fail_times=10))

    failed = db.query_one("SELECT id, status FROM evaluations WHERE run_id = ?", (run_id,))
    assert failed["status"] == "error"
    db.execute("UPDATE runs SET status = 'failed' WHERE id = ?", (run_id,))

    asyncio.run(retry_evaluation(db, cfg, FakeProvider(), rubric, failed["id"]))

    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["failed"] == 0
    assert run["status"] == "completed"
    usage = json.loads(run["usage_json"])
    assert usage["tokens_in"] > 0
    assert usage["tokens_out"] > 0


def test_retry_evaluation_rejects_unknown_and_ok(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(1)
    run_id = _run(db, cfg, rubric, batch_id, FakeProvider())
    ok_id = db.query_one("SELECT id FROM evaluations WHERE run_id = ?", (run_id,))["id"]

    with pytest.raises(LookupError):
        asyncio.run(retry_evaluation(db, cfg, FakeProvider(), rubric, "missing"))
    with pytest.raises(ValueError):
        asyncio.run(retry_evaluation(db, cfg, FakeProvider(), rubric, ok_id))


def test_pause_then_resume_via_manager(db, cfg, rubric, seed_batch) -> None:
    batch_id, _ = seed_batch(2)
    run_id = create_run(db, cfg, rubric, batch_id, "pause run")

    async def scenario() -> None:
        manager = RunManager(db, cfg, SlowFakeProvider(), rubric)
        assert manager.start(run_id) is True
        await asyncio.sleep(0.05)
        manager.pause(run_id)
        assert manager.start(run_id) is True

        async def wait_done() -> None:
            while manager.is_running(run_id):
                await asyncio.sleep(0.02)

        await asyncio.wait_for(wait_done(), timeout=5.0)

    asyncio.run(scenario())

    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert run["status"] == "completed"
    assert run["done"] == 2
