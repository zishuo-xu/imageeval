import sqlite3

import pytest

from imageeval.db import Database, mark_stale_runs, migrate


def test_migrate_creates_tables_and_is_idempotent(db: Database) -> None:
    names = {
        row["name"]
        for row in db.query("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
    }
    assert {
        "schema_version",
        "import_batches",
        "samples",
        "runs",
        "evaluations",
        "reviews",
        "v_evaluation_state",
    } <= names

    migrate(db.conn)
    assert db.query_one("SELECT version FROM schema_version")["version"] == 1

    columns = db.query("PRAGMA table_info(schema_version)")
    assert [(row["name"], row["pk"]) for row in columns] == [("version", 1)]


def test_foreign_keys_enforced(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, width, height, created_at) "
            "VALUES ('s1', 'missing', 'e1', 'q', 'p', 1, 1, 'now')"
        )


def test_mark_stale_runs_pauses_running(db: Database) -> None:
    db.execute(
        "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b1', 'x', 'now')"
    )
    db.execute(
        "INSERT INTO runs (id, name, batch_id, rubric_version, prompt_hash, provider, judge_model, status, created_at) "
        "VALUES ('r1', 'n', 'b1', 'v1', 'h', 'p', 'm', 'running', 'now')"
    )
    mark_stale_runs(db)
    assert db.query_one("SELECT status FROM runs WHERE id = 'r1'")["status"] == "paused"


def _seed_evaluation(db: Database) -> None:
    db.execute(
        "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b1', 'x', 'now')"
    )
    db.execute(
        "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, width, height, created_at) "
        "VALUES ('s1', 'b1', 'e1', 'q', 'p', 1, 1, 'now')"
    )
    db.execute(
        "INSERT INTO runs (id, name, batch_id, rubric_version, prompt_hash, provider, judge_model, created_at) "
        "VALUES ('r1', 'n', 'b1', 'v1', 'h', 'p', 'm', 'now')"
    )
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, created_at) "
        "VALUES ('e1', 's1', 'r1', 'done', 'now')"
    )


def test_transaction_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(
                "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b1', 'x', 'now')"
            )
            raise RuntimeError()
    assert db.query_one("SELECT COUNT(*) AS n FROM import_batches")["n"] == 0


def test_nested_transaction_rolls_back_as_unit(db: Database) -> None:
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(
                "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b1', 'x', 'now')"
            )
            with db.transaction():
                db.execute(
                    "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b2', 'x', 'now')"
                )
                raise RuntimeError()
    assert db.query("SELECT id FROM import_batches") == []


def test_view_state_transitions(db: Database) -> None:
    _seed_evaluation(db)
    assert (
        db.query_one("SELECT state FROM v_evaluation_state WHERE id = 'e1'")["state"]
        == "ai_done"
    )

    db.execute(
        "INSERT INTO reviews (id, evaluation_id, reviewer, decision, created_at) "
        "VALUES ('rv1', 'e1', 'tester', 'accepted', '2026-01-01T00:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO reviews (id, evaluation_id, reviewer, decision, created_at) "
        "VALUES ('rv2', 'e1', 'tester', 'corrected', '2026-01-02T00:00:00+00:00')"
    )
    assert (
        db.query_one("SELECT state FROM v_evaluation_state WHERE id = 'e1'")["state"]
        == "corrected"
    )

    db.execute("UPDATE evaluations SET status = 'error' WHERE id = 'e1'")
    assert (
        db.query_one("SELECT state FROM v_evaluation_state WHERE id = 'e1'")["state"]
        == "error"
    )


def test_wal_mode_enabled(db: Database) -> None:
    assert db.query_one("PRAGMA journal_mode")[0] == "wal"


def test_unique_constraints(db: Database) -> None:
    db.execute(
        "INSERT INTO import_batches (id, source_name, created_at) VALUES ('b1', 'x', 'now')"
    )
    db.execute(
        "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, width, height, created_at) "
        "VALUES ('s1', 'b1', 'e1', 'q', 'p', 1, 1, 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, width, height, created_at) "
            "VALUES ('s2', 'b1', 'e1', 'q', 'p', 1, 1, 'now')"
        )

    db.execute(
        "INSERT INTO runs (id, name, batch_id, rubric_version, prompt_hash, provider, judge_model, created_at) "
        "VALUES ('r1', 'n', 'b1', 'v1', 'h', 'p', 'm', 'now')"
    )
    db.execute(
        "INSERT INTO evaluations (id, sample_id, run_id, status, created_at) "
        "VALUES ('e1', 's1', 'r1', 'done', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO evaluations (id, sample_id, run_id, status, created_at) "
            "VALUES ('e2', 's1', 'r1', 'done', 'now')"
        )
