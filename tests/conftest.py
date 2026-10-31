from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from PIL import Image

from imageeval.config import AppConfig, JudgeConfig, PipelineConfig
from imageeval.db import Database, migrate


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data_dir=tmp_path / "data",
        judge=JudgeConfig(base_url="http://test.local/v1", model="fake-v1"),
        pipeline=PipelineConfig(max_concurrency=2, rpm=1000, max_retries=2),
        reviewer_name="tester",
    )


@pytest.fixture
def db(cfg: AppConfig):
    database = Database(cfg.db_path)
    migrate(database.conn)
    yield database
    database.close()


@pytest.fixture
def rubric():
    from imageeval.rubric.loader import load_rubric

    return load_rubric()


@pytest.fixture
def make_image(tmp_path: Path):
    def _make(name: str = "img.png", size: tuple[int, int] = (320, 240)) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (200, 120, 80)).save(path)
        return path

    return _make


@pytest.fixture
def seed_batch(db: Database, cfg: AppConfig, make_image):
    def _seed(n: int = 2, query: str = "一只红色的猫坐在窗台上") -> tuple[str, list[str]]:
        from imageeval.storage import make_thumbnail

        batch_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO import_batches (id, source_name, created_at, sample_count, rejected_count, report_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (batch_id, "test.csv", "2026-01-01T00:00:00+00:00", 0, 0, "[]"),
        )
        sample_ids: list[str] = []
        for i in range(n):
            src = make_image(f"seed_{batch_id}_{i}.png")
            dest = cfg.images_dir / batch_id / f"{i}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            thumb_rel = f"{batch_id}/{i}.jpg"
            make_thumbnail(dest, cfg.thumbs_dir / thumb_rel)
            sample_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, thumb_path, "
                "width, height, tags_json, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sample_id,
                    batch_id,
                    f"ext-{i}",
                    query,
                    f"{batch_id}/{i}.png",
                    thumb_rel,
                    320,
                    240,
                    "[]",
                    "{}",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            sample_ids.append(sample_id)
        db.execute("UPDATE import_batches SET sample_count = ? WHERE id = ?", (n, batch_id))
        return batch_id, sample_ids

    return _seed
