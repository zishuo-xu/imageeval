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


def test_foreign_keys_enforced(db: Database) -> None:
    import pytest

    with pytest.raises(Exception):
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
