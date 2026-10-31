from __future__ import annotations

import asyncio
import json
import random
import sys
import time
import uuid
from typing import Any

from .config import AppConfig
from .db import Database
from .judge.base import (
    FatalJudgeError,
    JudgeError,
    JudgeProvider,
    RetryableJudgeError,
    SchemaJudgeError,
)
from .rubric.loader import Rubric
from .scoring import compute_scores
from .storage import resolve_under
from .util import utcnow


class RunControl:
    def __init__(self) -> None:
        self.paused = False
        self.cancelled = False


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / max(1, rpm)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
                now = self._next
            self._next = now + self._interval


def _refresh_counts(db: Database, run_id: str) -> None:
    db.execute(
        "UPDATE runs SET "
        "done = (SELECT COUNT(*) FROM evaluations WHERE run_id = ? AND status = 'ok'), "
        "failed = (SELECT COUNT(*) FROM evaluations WHERE run_id = ? AND status = 'error') "
        "WHERE id = ?",
        (run_id, run_id, run_id),
    )


_UPSERT_SQL = """
INSERT INTO evaluations (
    id, sample_id, run_id, status, adherence_score, quality_score, aesthetics_score,
    overall_score, requirements_json, subscores_json, observation, verdict, raw_response,
    parse_attempts, error, latency_ms, tokens_in, tokens_out, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(sample_id, run_id) DO UPDATE SET
    status = excluded.status,
    adherence_score = excluded.adherence_score,
    quality_score = excluded.quality_score,
    aesthetics_score = excluded.aesthetics_score,
    overall_score = excluded.overall_score,
    requirements_json = excluded.requirements_json,
    subscores_json = excluded.subscores_json,
    observation = excluded.observation,
    verdict = excluded.verdict,
    raw_response = excluded.raw_response,
    parse_attempts = excluded.parse_attempts,
    error = excluded.error,
    latency_ms = excluded.latency_ms,
    tokens_in = excluded.tokens_in,
    tokens_out = excluded.tokens_out,
    created_at = excluded.created_at
WHERE evaluations.status = 'error'
"""


def _save_ok(
    db: Database,
    sample_id: str,
    run_id: str,
    response: Any,
    scores: Any,
) -> None:
    payload = response.parsed.model_dump()
    db.execute(
        _UPSERT_SQL,
        (
            uuid.uuid4().hex,
            sample_id,
            run_id,
            "ok",
            scores.adherence,
            scores.quality,
            scores.aesthetics,
            scores.overall,
            json.dumps(payload["requirements"], ensure_ascii=False),
            json.dumps(payload["subscores"], ensure_ascii=False),
            payload.get("observation", ""),
            payload.get("verdict", ""),
            response.raw,
            response.parse_attempts,
            None,
            response.latency_ms,
            response.tokens_in,
            response.tokens_out,
            utcnow(),
        ),
    )


def _save_error(db: Database, sample_id: str, run_id: str, error: str) -> None:
    db.execute(
        _UPSERT_SQL,
        (
            uuid.uuid4().hex,
            sample_id,
            run_id,
            "error",
            None,
            None,
            None,
            None,
            "[]",
            "{}",
            "",
            "",
            "",
            1,
            error,
            0,
            0,
            0,
            utcnow(),
        ),
    )


async def _evaluate_one(
    db: Database,
    cfg: AppConfig,
    provider: JudgeProvider,
    rubric: Rubric,
    run_id: str,
    sample: Any,
) -> None:
    try:
        image_path = resolve_under(cfg.images_dir, sample["image_path"])
    except Exception as exc:
        _save_error(db, sample["id"], run_id, f"image path error: {exc}")
        return
    last_error: Exception | None = None

    for attempt in range(cfg.pipeline.max_retries + 1):
        try:
            response = await provider.evaluate(sample["query_text"], image_path)
            scores = compute_scores(response.parsed, rubric)
            _save_ok(db, sample["id"], run_id, response, scores)
            return
        except RetryableJudgeError as exc:
            last_error = exc
            if attempt >= cfg.pipeline.max_retries:
                break
            await asyncio.sleep(min(2**attempt * 0.5 + random.random() * 0.5, 10))
        except (SchemaJudgeError, FatalJudgeError, JudgeError) as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break

    _save_error(db, sample["id"], run_id, str(last_error) if last_error else "unknown error")


async def execute_run(
    db: Database,
    cfg: AppConfig,
    provider: JudgeProvider,
    rubric: Rubric,
    run_id: str,
    control: RunControl | None = None,
) -> None:
    control = control or RunControl()
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise ValueError(f"run not found: {run_id}")

    batch_id = run["batch_id"]
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM samples WHERE batch_id = ?", (batch_id,)
    )["c"]
    db.execute(
        "UPDATE runs SET status = 'running', started_at = COALESCE(started_at, ?), total = ? "
        "WHERE id = ?",
        (utcnow(), total, run_id),
    )

    pending = db.query(
        "SELECT s.id, s.query_text, s.image_path FROM samples s "
        "WHERE s.batch_id = ? AND NOT EXISTS ("
        "  SELECT 1 FROM evaluations e WHERE e.sample_id = s.id AND e.run_id = ? AND e.status = 'ok'"
        ") ORDER BY s.created_at",
        (batch_id, run_id),
    )

    queue: asyncio.Queue = asyncio.Queue()
    for row in pending:
        queue.put_nowait(row)

    limiter = RateLimiter(cfg.pipeline.rpm)

    async def worker() -> None:
        while True:
            if control.cancelled:
                return
            while control.paused and not control.cancelled:
                await asyncio.sleep(0.5)
            if control.cancelled:
                return
            try:
                sample = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await limiter.acquire()
            if control.cancelled:
                return
            try:
                await _evaluate_one(db, cfg, provider, rubric, run_id, sample)
                _refresh_counts(db, run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                try:
                    _save_error(db, sample["id"], run_id, f"worker error: {exc}")
                except Exception:
                    pass
                try:
                    _refresh_counts(db, run_id)
                except Exception:
                    pass

    workers = [
        asyncio.create_task(worker())
        for _ in range(max(1, cfg.pipeline.max_concurrency))
    ]
    results = await asyncio.gather(*workers, return_exceptions=True)
    worker_errors = [r for r in results if isinstance(r, BaseException)]

    _refresh_counts(db, run_id)
    progress = db.query_one(
        "SELECT done, failed FROM runs WHERE id = ?", (run_id,)
    )
    incomplete = (progress["done"] + progress["failed"]) < total

    usage = db.query_one(
        "SELECT COALESCE(SUM(tokens_in), 0) AS ti, COALESCE(SUM(tokens_out), 0) AS to_, "
        "COALESCE(SUM(latency_ms), 0) AS lm FROM evaluations WHERE run_id = ?",
        (run_id,),
    )
    if control.cancelled:
        status = "cancelled"
    elif worker_errors or incomplete:
        status = "failed"
    else:
        status = "completed"
    db.execute(
        "UPDATE runs SET status = ?, finished_at = ?, usage_json = ? WHERE id = ?",
        (
            status,
            utcnow(),
            json.dumps(
                {
                    "tokens_in": usage["ti"],
                    "tokens_out": usage["to_"],
                    "latency_ms": usage["lm"],
                }
            ),
            run_id,
        ),
    )
    _refresh_counts(db, run_id)


class RunManager:
    def __init__(
        self,
        db: Database,
        cfg: AppConfig,
        provider: JudgeProvider,
        rubric: Rubric,
    ):
        self._db = db
        self._cfg = cfg
        self._provider = provider
        self._rubric = rubric
        self._tasks: dict[str, asyncio.Task] = {}
        self._controls: dict[str, RunControl] = {}

    def is_running(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def start(self, run_id: str) -> bool:
        if self.is_running(run_id):
            control = self._controls.get(run_id)
            if control is not None and control.paused:
                control.paused = False
                self._db.execute(
                    "UPDATE runs SET status = 'running' WHERE id = ? AND status = 'paused'",
                    (run_id,),
                )
                return True
            return False
        control = RunControl()
        self._controls[run_id] = control
        task = asyncio.create_task(
            execute_run(
                self._db, self._cfg, self._provider, self._rubric, run_id, control
            )
        )
        self._tasks[run_id] = task

        def _done(task: asyncio.Task) -> None:
            self._tasks.pop(run_id, None)
            if not task.cancelled() and task.exception() is not None:
                print(f"run {run_id} task failed: {task.exception()}", file=sys.stderr)

        task.add_done_callback(_done)
        return True

    def pause(self, run_id: str) -> None:
        control = self._controls.get(run_id)
        if control is not None:
            control.paused = True
        self._db.execute(
            "UPDATE runs SET status = 'paused' WHERE id = ? AND status = 'running'",
            (run_id,),
        )

    def cancel(self, run_id: str) -> None:
        control = self._controls.get(run_id)
        if control is not None:
            control.cancelled = True
        self._db.execute(
            "UPDATE runs SET status = 'cancelled' WHERE id = ? AND status IN ('running', 'paused')",
            (run_id,),
        )
