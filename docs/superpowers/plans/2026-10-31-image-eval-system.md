# 生图模型评测系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建本地 Web 评测工具：导入「原始 Query + 生成图片」，用云端多模态 API 按三维度自动评分，支持人工复核与标注沉淀，输出可视化报告与训练数据集。

**Architecture:** FastAPI 单进程 + SQLite（WAL）+ 原生 JS 前端。评分标准文件化（rubric v1），裁判走 Provider 协议（OpenAI 兼容实现 + Fake 实现），AI 分与人工分双轨存储，人工复核 append-only。

**Tech Stack:** Python 3.14、FastAPI、Uvicorn、httpx、pydantic v2、PyYAML、Pillow、SQLite、原生 JS、Chart.js（本地 vendored）、pytest / pytest-asyncio。

## Global Constraints

- Python `>=3.14`；依赖用 `uv` 管理，所有命令通过 `uv run` 执行。
- 评分尺度统一为 **1–5 整数**（人工分）；AI 维度分为两位小数浮点。
- 权重唯一来源是 `src/imageeval/rubric/v1.yaml`；不得在配置文件或代码里重复定义维度权重。
- 时间戳一律 UTC ISO-8601 字符串（`datetime.now(timezone.utc).isoformat()`）。
- API key 只从环境变量读取（变量名由配置的 `api_key_env` 指定），配置文件和日志中不得出现密钥。
- 测试**永不**发起真实网络请求；外部 HTTP 一律用 `httpx.MockTransport` 或 `FakeProvider`。
- `evaluations` 只增不改（除 error 重试覆盖）；`reviews` 只能追加，绝不更新或删除。
- 训练数据导出必须区分 `gold`（人工复核）/ `silver`（仅 AI），默认不混用。
- 前端为中文界面，无构建步骤，不引入 npm。
- 任何图片文件访问都必须经 `resolve_under()` 做真实路径校验。

## 学习点（不能由代理直接完成）

- **Task 4 Step 3**：`scoring.aggregate_adherence()` 的权重与惩罚策略由用户实现。
- **Task 10 Step 5**：`report.select_failure_cases()` 的失败判定规则由用户实现。

执行到这两个 Step 时必须暂停，请用户实现；用户明确委托时才使用附录 A 的参考实现。

---

## Task 1: 项目骨架与配置

**Files:**
- Create: `pyproject.toml`
- Create: `config.example.toml`
- Create: `src/imageeval/__init__.py`
- Create: `src/imageeval/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `AppConfig(data_dir: Path, host: str, port: int, reviewer_name: str, rubric_path: Path, judge: JudgeConfig, pipeline: PipelineConfig)`，属性 `db_path`、`images_dir`、`thumbs_dir`、`exports_dir`、`reports_dir`、方法 `api_key() -> str | None`
  - `load_config(path: Path | None = None, data_dir: Path | None = None) -> AppConfig`
  - `JudgeConfig`、`PipelineConfig`、`DEFAULT_RUBRIC`

- [ ] **Step 1: 创建项目文件**

`pyproject.toml`：

```toml
[project]
name = "imageeval"
version = "0.1.0"
description = "生图模型评测系统"
requires-python = ">=3.14"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "httpx>=0.27",
  "pydantic>=2.8",
  "PyYAML>=6.0",
  "pillow>=11.0",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24"]

[project.scripts]
imageeval = "imageeval.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/imageeval"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`config.example.toml`：

```toml
[server]
host = "127.0.0.1"
port = 8765

[judge]
provider = "openai_compat"
base_url = "https://your-endpoint.example.com/v1"
model = "your-vision-model"
api_key_env = "IMAGEEVAL_API_KEY"
temperature = 0.2
max_tokens = 1200
timeout_s = 90
image_max_edge = 1280

[pipeline]
max_concurrency = 4
rpm = 60
max_retries = 3

[reviewer]
default_name = "local"
```

`src/imageeval/__init__.py`：

```python
"""imageeval: 生图模型评测系统。"""

__version__ = "0.1.0"
```

- [ ] **Step 2: 写失败测试**

`tests/test_config.py`：

```python
from pathlib import Path

from imageeval.config import DEFAULT_RUBRIC, load_config


def test_load_config_reads_all_sections(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[server]
host = "0.0.0.0"
port = 9000

[judge]
base_url = "http://example.test/v1"
model = "vision-test"
api_key_env = "MY_TEST_KEY"
temperature = 0.3
image_max_edge = 1024

[pipeline]
max_concurrency = 2
rpm = 30
max_retries = 2

[reviewer]
default_name = "alice"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_TEST_KEY", "secret")

    cfg = load_config(cfg_file, data_dir=tmp_path / "data")

    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.db_path == tmp_path / "data" / "imageeval.db"
    assert cfg.judge.model == "vision-test"
    assert cfg.judge.temperature == 0.3
    assert cfg.judge.image_max_edge == 1024
    assert cfg.pipeline.max_concurrency == 2
    assert cfg.pipeline.rpm == 30
    assert cfg.reviewer_name == "alice"
    assert cfg.api_key() == "secret"


def test_defaults_without_config_file(tmp_path: Path) -> None:
    cfg = load_config(None, data_dir=tmp_path)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.rubric_path == DEFAULT_RUBRIC
    assert cfg.reviewer_name == "local"
    assert cfg.api_key() is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv sync --extra dev && uv run pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.config'`

- [ ] **Step 4: 实现配置模块**

`src/imageeval/config.py`：

```python
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_RUBRIC = Path(__file__).parent / "rubric" / "v1.yaml"


@dataclass(frozen=True)
class JudgeConfig:
    provider: str = "openai_compat"
    base_url: str = ""
    model: str = ""
    api_key_env: str = "IMAGEEVAL_API_KEY"
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout_s: float = 90.0
    image_max_edge: int = 1280


@dataclass(frozen=True)
class PipelineConfig:
    max_concurrency: int = 4
    rpm: int = 60
    max_retries: int = 3


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8765
    reviewer_name: str = "local"
    rubric_path: Path = DEFAULT_RUBRIC
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "imageeval.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def api_key(self) -> str | None:
        return os.environ.get(self.judge.api_key_env)


def load_config(path: Path | None = None, data_dir: Path | None = None) -> AppConfig:
    raw: dict = {}
    if path is not None:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)

    server = raw.get("server", {})
    judge = raw.get("judge", {})
    pipeline = raw.get("pipeline", {})
    reviewer = raw.get("reviewer", {})

    return AppConfig(
        data_dir=Path(data_dir) if data_dir is not None else Path(raw.get("data_dir", "data")),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8765)),
        reviewer_name=reviewer.get("default_name", "local"),
        rubric_path=Path(raw["rubric_path"]) if "rubric_path" in raw else DEFAULT_RUBRIC,
        judge=JudgeConfig(**judge),
        pipeline=PipelineConfig(**pipeline),
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: `2 passed`

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml config.example.toml src/imageeval/__init__.py src/imageeval/config.py tests/test_config.py
git commit -m "feat: 项目骨架与配置加载"
```

---

## Task 2: 数据库与迁移

**Files:**
- Create: `src/imageeval/db.py`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`（空文件）
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `AppConfig`（Task 1）
- Produces:
  - `Database(path: Path)`：`.conn`、`.query(sql, params=()) -> list[sqlite3.Row]`、`.query_one(...) -> sqlite3.Row | None`、`.execute(...) -> sqlite3.Cursor`、`.executemany(...)`、`.transaction()`、`.close()`
  - `migrate(conn: sqlite3.Connection) -> None`（幂等）
  - `mark_stale_runs(db: Database) -> None`
  - 表：`schema_version`、`import_batches`、`samples`、`runs`、`evaluations`、`reviews`；视图 `v_evaluation_state`
  - 测试夹具：`cfg`、`db`、`rubric`、`make_image`、`seed_batch`

- [ ] **Step 1: 写失败测试与夹具**

`tests/conftest.py`：

```python
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
```

同时创建空文件 `tests/__init__.py`（供后续 `from tests.helpers import ...` 使用）。

`tests/test_db.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.db'`（`conftest` 会先因 `imageeval.storage` 缺失报错，属于预期）

- [ ] **Step 3: 实现数据库模块**

`src/imageeval/db.py`：

```python
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    report_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS samples (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    image_path TEXT NOT NULL,
    thumb_path TEXT,
    ref_image_path TEXT,
    model_name TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, external_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES import_batches(id),
    rubric_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    adherence_score REAL,
    quality_score REAL,
    aesthetics_score REAL,
    overall_score REAL,
    requirements_json TEXT NOT NULL DEFAULT '[]',
    subscores_json TEXT NOT NULL DEFAULT '{}',
    observation TEXT,
    verdict TEXT,
    raw_response TEXT,
    parse_attempts INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    latency_ms INTEGER,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(sample_id, run_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    human_adherence INTEGER,
    human_quality INTEGER,
    human_aesthetics INTEGER,
    human_overall REAL,
    reasons_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_batch ON samples(batch_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_run ON evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_reviews_evaluation ON reviews(evaluation_id);

CREATE VIEW IF NOT EXISTS v_evaluation_state AS
SELECT
    e.*,
    CASE
        WHEN e.status = 'error' THEN 'error'
        WHEN lr.id IS NULL THEN 'ai_done'
        ELSE lr.decision
    END AS state
FROM evaluations e
LEFT JOIN (
    SELECT r.*, ROW_NUMBER() OVER (
        PARTITION BY r.evaluation_id ORDER BY r.created_at DESC, r.id DESC
    ) AS rn
    FROM reviews r
) lr ON lr.evaluation_id = e.id AND lr.rn = 1;
"""

MIGRATIONS: dict[int, str] = {1: SCHEMA_V1}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        current = 0
    else:
        current = int(row["version"] if isinstance(row, sqlite3.Row) else row[0])

    for version in sorted(MIGRATIONS):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            conn.execute("UPDATE schema_version SET version = ?", (version,))
            conn.commit()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def mark_stale_runs(db: Database) -> None:
    db.execute("UPDATE runs SET status = 'paused' WHERE status = 'running'")
```

`tests/conftest.py` 的 `seed_batch` 在函数内延迟导入 `make_thumbnail`，因此 Task 2 的测试不依赖 Task 5 的 `storage` 模块。同时创建空文件 `tests/__init__.py`，保证 `from tests.helpers import ...` 可用。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add src/imageeval/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: SQLite schema、迁移与测试夹具"
```

---

## Task 3: 评分契约模型

**Files:**
- Create: `src/imageeval/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Requirement(text, category, criticality, status, evidence)`
  - `SubScore(score: int | None, reason: str, na: bool)`
  - `QualitySubscores`（clarity/artifacts/text_render/physics/consistency）、`AestheticSubscores`（composition/color/lighting/texture/appeal）、`Subscores`
  - `JudgeOutput(observation, requirements, intent_alignment, subscores, notable_issues, verdict)`
  - `ReviewSubmit(decision, human_adherence, human_quality, human_aesthetics, reasons, note, duration_ms)`
  - `parse_judge_output(content: str) -> JudgeOutput`

- [ ] **Step 1: 写失败测试**

`tests/test_models.py`：

```python
import json

import pytest
from pydantic import ValidationError

from imageeval.models import JudgeOutput, ReviewSubmit, SubScore, parse_judge_output


def _valid_payload() -> dict:
    return {
        "observation": "画面中有一只红色的猫坐在窗台上。",
        "requirements": [
            {
                "text": "红色的猫",
                "category": "subject",
                "criticality": "critical",
                "status": "satisfied",
                "evidence": "画面中央的猫为红色",
            }
        ],
        "intent_alignment": 4,
        "subscores": {
            "quality": {
                "clarity": {"score": 4, "reason": "清晰"},
                "artifacts": {"score": 3, "reason": "轻微畸变"},
                "text_render": {"score": None, "reason": "无文字", "na": True},
                "physics": {"score": 4, "reason": "合理"},
                "consistency": {"score": 4, "reason": "一致"},
            },
            "aesthetics": {
                "composition": {"score": 4, "reason": "稳定"},
                "color": {"score": 5, "reason": "和谐"},
                "lighting": {"score": 4, "reason": "自然"},
                "texture": {"score": 3, "reason": "一般"},
                "appeal": {"score": 4, "reason": "有吸引力"},
            },
        },
        "notable_issues": [],
        "verdict": "整体符合要求",
    }


def test_parse_valid_output() -> None:
    output = parse_judge_output(json.dumps(_valid_payload(), ensure_ascii=False))
    assert output.intent_alignment == 4
    assert output.requirements[0].status == "satisfied"
    assert output.subscores.quality.text_render.na is True


def test_parse_strips_markdown_fence() -> None:
    content = "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    assert parse_judge_output(content).verdict == "整体符合要求"


def test_float_scores_are_rounded() -> None:
    data = _valid_payload()
    data["subscores"]["quality"]["clarity"]["score"] = 3.6
    data["intent_alignment"] = 4.4
    output = JudgeOutput.model_validate(data)
    assert output.subscores.quality.clarity.score == 4
    assert output.intent_alignment == 4


def test_requires_at_least_one_critical_requirement() -> None:
    data = _valid_payload()
    data["requirements"][0]["criticality"] = "normal"
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(data)


def test_non_na_subscore_requires_score() -> None:
    with pytest.raises(ValidationError):
        SubScore(score=None, reason="", na=False)


def test_corrected_review_requires_three_scores() -> None:
    with pytest.raises(ValidationError):
        ReviewSubmit(decision="corrected", human_adherence=4)
    ReviewSubmit(
        decision="corrected",
        human_adherence=4,
        human_quality=3,
        human_aesthetics=4,
    )


def test_accepted_review_allows_empty_scores() -> None:
    payload = ReviewSubmit(decision="accepted")
    assert payload.human_adherence is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.models'`

- [ ] **Step 3: 实现模型**

`src/imageeval/models.py`：

```python
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

Score = Annotated[int, Field(ge=1, le=5)]
Category = Literal["subject", "attribute", "count", "relation", "style", "text_render", "negative"]
Criticality = Literal["critical", "normal"]
Status = Literal["satisfied", "partial", "missing", "contradicted"]


class Requirement(BaseModel):
    text: str = Field(min_length=1)
    category: Category
    criticality: Criticality
    status: Status
    evidence: str = ""


class SubScore(BaseModel):
    score: Score | None = None
    reason: str = ""
    na: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        score = data.get("score")
        na = bool(data.get("na", False))
        if isinstance(score, float):
            score = int(round(score))
        if na:
            score = None
        return {**data, "score": score, "na": na}

    @model_validator(mode="after")
    def _require_score_unless_na(self) -> "SubScore":
        if not self.na and self.score is None:
            raise ValueError("score is required unless na=true")
        return self


class QualitySubscores(BaseModel):
    clarity: SubScore
    artifacts: SubScore
    text_render: SubScore
    physics: SubScore
    consistency: SubScore


class AestheticSubscores(BaseModel):
    composition: SubScore
    color: SubScore
    lighting: SubScore
    texture: SubScore
    appeal: SubScore


class Subscores(BaseModel):
    quality: QualitySubscores
    aesthetics: AestheticSubscores


class JudgeOutput(BaseModel):
    observation: str = ""
    requirements: list[Requirement] = Field(min_length=1)
    intent_alignment: Score
    subscores: Subscores
    notable_issues: list[str] = Field(default_factory=list)
    verdict: str = ""

    @model_validator(mode="before")
    @classmethod
    def _round_intent_alignment(cls, data: Any) -> Any:
        if isinstance(data, dict):
            value = data.get("intent_alignment")
            if isinstance(value, float):
                data = {**data, "intent_alignment": int(round(value))}
        return data

    @model_validator(mode="after")
    def _require_critical(self) -> "JudgeOutput":
        if not any(item.criticality == "critical" for item in self.requirements):
            raise ValueError("at least one requirement must be critical")
        return self


class ReviewSubmit(BaseModel):
    decision: Literal["accepted", "corrected", "skipped"]
    human_adherence: Score | None = None
    human_quality: Score | None = None
    human_aesthetics: Score | None = None
    reasons: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    duration_ms: int = 0

    @model_validator(mode="after")
    def _corrected_requires_scores(self) -> "ReviewSubmit":
        if self.decision == "corrected":
            for field in ("human_adherence", "human_quality", "human_aesthetics"):
                if getattr(self, field) is None:
                    raise ValueError(f"{field} is required when decision=corrected")
        return self


def parse_judge_output(content: str) -> JudgeOutput:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in response")
    data = json.loads(text[start : end + 1])
    return JudgeOutput.model_validate(data)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_models.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```bash
git add src/imageeval/models.py tests/test_models.py
git commit -m "feat: 评分 JSON 契约与校验"
```

---

## Task 4: Rubric v1 与确定性分数聚合（含学习点）

**Files:**
- Create: `src/imageeval/rubric/__init__.py`
- Create: `src/imageeval/rubric/v1.yaml`
- Create: `src/imageeval/rubric/loader.py`
- Create: `src/imageeval/scoring.py`
- Test: `tests/test_rubric.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `JudgeOutput`、`Requirement`、`SubScore`（Task 3）
- Produces:
  - `Rubric(version, anchors, dimension_weights, subscore_weights)`
  - `load_rubric(path: Path | None = None) -> Rubric`
  - `QUALITY_KEYS`、`AESTHETICS_KEYS`
  - `aggregate_adherence(requirements: list[Requirement], intent_alignment: int) -> float`
  - `compute_scores(output: JudgeOutput, rubric: Rubric) -> EvaluationScores`
  - `compute_overall(adherence: float, quality: float, aesthetics: float, rubric: Rubric) -> float`
  - `EvaluationScores(adherence, quality, aesthetics, overall)`

- [ ] **Step 1: 写失败测试**

`tests/test_rubric.py`：

```python
import pytest

from imageeval.rubric.loader import AESTHETICS_KEYS, QUALITY_KEYS, load_rubric


def test_load_v1_rubric() -> None:
    rubric = load_rubric()
    assert rubric.version == "v1"
    assert set(rubric.dimension_weights) == {"adherence", "quality", "aesthetics"}
    assert sum(rubric.dimension_weights.values()) == pytest.approx(1.0)
    assert set(rubric.subscore_weights["quality"]) == set(QUALITY_KEYS)
    assert set(rubric.subscore_weights["aesthetics"]) == set(AESTHETICS_KEYS)
    assert sum(rubric.subscore_weights["quality"].values()) == pytest.approx(1.0)
    assert set(rubric.anchors) == {1, 2, 3, 4, 5}


def test_invalid_weights_rejected(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
version: bad
anchors:
  1: a
  2: b
  3: c
  4: d
  5: e
dimensions:
  adherence: {weight: 0.5}
  quality: {weight: 0.5, subscores: {clarity: 1.0}}
  aesthetics: {weight: 0.5, subscores: {composition: 1.0}}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_rubric(path)
```

`tests/test_scoring.py`：

```python
import pytest

from imageeval.models import JudgeOutput, Requirement, SubScore
from imageeval.scoring import aggregate_adherence, compute_overall, compute_scores


def _req(criticality="critical", status="satisfied") -> Requirement:
    return Requirement(
        text="x", category="subject", criticality=criticality, status=status
    )


def _output(adherence_status="satisfied", intent=5, quality=4, aesthetics=4) -> JudgeOutput:
    def sub(score):
        return SubScore(score=score, reason="r")

    return JudgeOutput.model_validate(
        {
            "observation": "o",
            "requirements": [
                {
                    "text": "主体",
                    "category": "subject",
                    "criticality": "critical",
                    "status": adherence_status,
                    "evidence": "e",
                }
            ],
            "intent_alignment": intent,
            "subscores": {
                "quality": {
                    "clarity": {"score": quality, "reason": "r"},
                    "artifacts": {"score": quality, "reason": "r"},
                    "text_render": {"score": None, "reason": "na", "na": True},
                    "physics": {"score": quality, "reason": "r"},
                    "consistency": {"score": quality, "reason": "r"},
                },
                "aesthetics": {
                    "composition": {"score": aesthetics, "reason": "r"},
                    "color": {"score": aesthetics, "reason": "r"},
                    "lighting": {"score": aesthetics, "reason": "r"},
                    "texture": {"score": aesthetics, "reason": "r"},
                    "appeal": {"score": aesthetics, "reason": "r"},
                },
            },
            "notable_issues": [],
            "verdict": "v",
        }
    )


def test_all_satisfied_reaches_max() -> None:
    assert aggregate_adherence([_req()], 5) == pytest.approx(5.0)


def test_partial_credit_and_normal_weight() -> None:
    reqs = [_req("critical", "satisfied"), _req("normal", "partial")]
    assert aggregate_adherence(reqs, 5) == pytest.approx(4.62, abs=0.01)


def test_critical_contradiction_caps_atomic_component() -> None:
    assert aggregate_adherence([_req("critical", "contradicted")], 5) == pytest.approx(3.5)


def test_compute_scores_uses_rubric_weights(rubric) -> None:
    scores = compute_scores(_output(quality=4, aesthetics=4), rubric)
    assert scores.adherence == pytest.approx(5.0)
    assert scores.quality == pytest.approx(4.0)
    assert scores.aesthetics == pytest.approx(4.0)
    assert scores.overall == pytest.approx(4.4)


def test_na_renormalizes_quality(rubric) -> None:
    output = _output(quality=4)
    output.subscores.quality.artifacts = SubScore(score=2, reason="bad")
    scores = compute_scores(output, rubric)
    expected = (0.20 * 4 + 0.30 * 2 + 0.20 * 4 + 0.20 * 4) / 0.90
    assert scores.quality == pytest.approx(round(expected, 2))


def test_insufficient_subscores_raises(rubric) -> None:
    output = _output()
    output.subscores.quality.clarity = SubScore(score=None, reason="na", na=True)
    output.subscores.quality.physics = SubScore(score=None, reason="na", na=True)
    output.subscores.quality.consistency = SubScore(score=None, reason="na", na=True)
    with pytest.raises(ValueError, match="insufficient applicable"):
        compute_scores(output, rubric)


def test_compute_overall(rubric) -> None:
    assert compute_overall(4, 3, 5, rubric) == pytest.approx(3.9)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_rubric.py tests/test_scoring.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.rubric'`

- [ ] **Step 3（学习点，默认由用户完成）: 实现 `aggregate_adherence`**

在 `src/imageeval/scoring.py` 中实现：

```python
def aggregate_adherence(requirements: list[Requirement], intent_alignment: int) -> float:
    """把原子需求状态聚合成 1-5 的需求遵循分（两位小数）。

    约束：
    - critical 需求权重高于 normal（默认 3:1）。
    - partial 记半分，missing / contradicted 记 0。
    - 任一 critical 需求为 contradicted 时，atomic 分必须封顶（默认 3.0），
      但整体意图分仍按权重参与最终计算。
    - 最终分 = 0.75 × atomic 分 + 0.25 × intent_alignment。
    - requirements 为空时抛 ValueError。
    """
```

实现前先自己决定：critical 权重、封顶值、意图分占比是否符合你的业务侧重。若采用与测试不同的策略，先修改 `tests/test_scoring.py` 中的期望值再实现。

**参考实现见附录 A.1；仅在用户明确委托时使用。**

- [ ] **Step 4: 实现 rubric 与其余聚合逻辑**

`src/imageeval/rubric/__init__.py`：

```python
"""评分标准（rubric）加载。"""
```

`src/imageeval/rubric/v1.yaml`：

```yaml
version: v1
anchors:
  1: 严重问题，不可用
  2: 明显问题，需要重做
  3: 基本可用，存在可见瑕疵
  4: 良好，仅有轻微瑕疵
  5: 优秀，无明显问题
dimensions:
  adherence:
    weight: 0.40
  quality:
    weight: 0.35
    subscores:
      clarity: 0.20
      artifacts: 0.30
      text_render: 0.10
      physics: 0.20
      consistency: 0.20
  aesthetics:
    weight: 0.25
    subscores:
      composition: 0.20
      color: 0.20
      lighting: 0.20
      texture: 0.20
      appeal: 0.20
```

`src/imageeval/rubric/loader.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_RUBRIC_PATH = Path(__file__).parent / "v1.yaml"

QUALITY_KEYS = ("clarity", "artifacts", "text_render", "physics", "consistency")
AESTHETICS_KEYS = ("composition", "color", "lighting", "texture", "appeal")
DIMENSION_KEYS = ("adherence", "quality", "aesthetics")


@dataclass(frozen=True)
class Rubric:
    version: str
    anchors: dict[int, str]
    dimension_weights: dict[str, float]
    subscore_weights: dict[str, dict[str, float]]


def _check_sum(weights: dict[str, float], label: str) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{label} weights must sum to 1.0, got {total}")


def load_rubric(path: Path | None = None) -> Rubric:
    path = Path(path) if path is not None else DEFAULT_RUBRIC_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rubric must be a mapping")

    version = str(data.get("version", "")).strip()
    if not version:
        raise ValueError("rubric.version is required")

    anchors = {int(k): str(v) for k, v in (data.get("anchors") or {}).items()}
    if set(anchors) != {1, 2, 3, 4, 5}:
        raise ValueError("rubric.anchors must define keys 1..5")

    dims = data.get("dimensions") or {}
    if set(dims) != set(DIMENSION_KEYS):
        raise ValueError(f"rubric.dimensions must be {DIMENSION_KEYS}")

    dimension_weights = {key: float(dims[key]["weight"]) for key in DIMENSION_KEYS}
    _check_sum(dimension_weights, "dimension")

    subscore_weights: dict[str, dict[str, float]] = {}
    for dim, expected in (("quality", QUALITY_KEYS), ("aesthetics", AESTHETICS_KEYS)):
        raw = dims[dim].get("subscores") or {}
        weights = {str(k): float(v) for k, v in raw.items()}
        if set(weights) != set(expected):
            raise ValueError(f"{dim} subscores must be {expected}")
        _check_sum(weights, dim)
        subscore_weights[dim] = weights

    return Rubric(
        version=version,
        anchors=anchors,
        dimension_weights=dimension_weights,
        subscore_weights=subscore_weights,
    )
```

`src/imageeval/scoring.py`（`aggregate_adherence` 替换为用户实现；其余如下）：

```python
from __future__ import annotations

from dataclasses import dataclass

from .models import JudgeOutput, Requirement, SubScore
from .rubric.loader import Rubric


@dataclass(frozen=True)
class EvaluationScores:
    adherence: float
    quality: float
    aesthetics: float
    overall: float


def aggregate_adherence(requirements: list[Requirement], intent_alignment: int) -> float:
    # 学习点：由用户实现，参考实现见附录 A.1
    raise NotImplementedError


def _dimension_score(subscores: dict[str, SubScore], weights: dict[str, float]) -> float:
    applicable = {
        key: item
        for key, item in subscores.items()
        if not item.na and item.score is not None
    }
    if len(applicable) * 2 < len(subscores):
        raise ValueError("insufficient applicable subscores")
    weight_sum = sum(weights[key] for key in applicable)
    score = sum(weights[key] * applicable[key].score for key in applicable) / weight_sum
    return round(score, 2)


def compute_overall(
    adherence: float, quality: float, aesthetics: float, rubric: Rubric
) -> float:
    w = rubric.dimension_weights
    return round(
        w["adherence"] * adherence + w["quality"] * quality + w["aesthetics"] * aesthetics,
        2,
    )


def compute_scores(output: JudgeOutput, rubric: Rubric) -> EvaluationScores:
    adherence = aggregate_adherence(output.requirements, output.intent_alignment)
    quality = _dimension_score(dict(output.subscores.quality), rubric.subscore_weights["quality"])
    aesthetics = _dimension_score(
        dict(output.subscores.aesthetics), rubric.subscore_weights["aesthetics"]
    )
    overall = compute_overall(adherence, quality, aesthetics, rubric)
    return EvaluationScores(
        adherence=adherence,
        quality=quality,
        aesthetics=aesthetics,
        overall=overall,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_rubric.py tests/test_scoring.py -v`
Expected: `9 passed`

- [ ] **Step 6: 提交**

```bash
git add src/imageeval/rubric src/imageeval/scoring.py tests/test_rubric.py tests/test_scoring.py
git commit -m "feat: rubric v1 与确定性分数聚合"
```

---

## Task 5: 图片存储与导入

**Files:**
- Create: `src/imageeval/storage.py`
- Create: `src/imageeval/importer.py`
- Create: `src/imageeval/__main__.py`（仅 `import` 子命令）
- Test: `tests/test_storage.py`
- Test: `tests/test_import.py`

**Interfaces:**
- Consumes: `AppConfig`、`Database`、`samples`/`import_batches` 表
- Produces:
  - `ensure_data_dirs(cfg) -> None`
  - `resolve_under(root: Path, relative: str) -> Path`
  - `validate_image(path: Path) -> tuple[int, int]`
  - `make_thumbnail(src: Path, dst: Path, max_edge: int = 480) -> None`
  - `downscale_bytes(path: Path, max_edge: int) -> tuple[bytes, str]`
  - `image_data_url(path: Path, max_edge: int) -> str`
  - `import_file(db, cfg, source_path, image_root=None, download=False) -> ImportResult`
  - `ImportResult(batch_id, imported, rejected, report)`

- [ ] **Step 1: 写失败测试**

`tests/test_storage.py`：

```python
import base64
import io

import pytest
from PIL import Image

from imageeval.storage import (
    downscale_bytes,
    image_data_url,
    make_thumbnail,
    resolve_under,
    validate_image,
)


def test_validate_image_returns_size(make_image) -> None:
    path = make_image("a.png", (300, 200))
    assert validate_image(path) == (300, 200)


def test_validate_image_rejects_text(tmp_path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="invalid image"):
        validate_image(bad)


def test_resolve_under_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.png").write_bytes(b"x")
    assert resolve_under(root, "ok.png") == (root / "ok.png").resolve()
    with pytest.raises(ValueError):
        resolve_under(root, "../escape.png")


def test_make_thumbnail_limits_edge(make_image, tmp_path) -> None:
    src = make_image("big.png", (2000, 1000))
    dst = tmp_path / "thumb.jpg"
    make_thumbnail(src, dst, max_edge=480)
    with Image.open(dst) as im:
        assert max(im.size) == 480


def test_downscale_bytes_and_data_url(make_image) -> None:
    src = make_image("wide.png", (2000, 1000))
    data, mime = downscale_bytes(src, 640)
    assert mime in {"image/jpeg", "image/png"}
    with Image.open(io.BytesIO(data)) as im:
        assert max(im.size) == 640

    url = image_data_url(src, 640)
    assert url.startswith("data:image/")
    assert ";base64," in url
    raw = base64.b64decode(url.split(",", 1)[1])
    assert len(raw) > 100
```

`tests/test_import.py`：

```python
import json

from imageeval.importer import import_file


def test_import_csv_with_bad_row(db, cfg, make_image, tmp_path) -> None:
    img1 = make_image("one.png", (100, 80))
    img2 = make_image("two.png", (120, 90))
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "external_id,query,image,model_name,tags\n"
        f"a1,一只红猫,{img1.name},m1,tag1;tag2\n"
        "a2,坏图,missing.png,m1,\n"
        f"a3,一只蓝狗,{img2.name},m1,\n",
        encoding="utf-8",
    )

    result = import_file(db, cfg, csv_path)

    assert result.imported == 2
    assert result.rejected == 1
    assert result.report[0]["external_id"] == "a2"
    rows = db.query("SELECT * FROM samples WHERE batch_id = ? ORDER BY external_id", (result.batch_id,))
    assert [row["external_id"] for row in rows] == ["a1", "a3"]
    assert json.loads(rows[0]["tags_json"]) == ["tag1", "tag2"]
    assert (cfg.images_dir / rows[0]["image_path"]).exists()
    assert (cfg.thumbs_dir / rows[0]["thumb_path"]).exists()


def test_import_jsonl_and_duplicate_id(db, cfg, make_image, tmp_path) -> None:
    img = make_image("dup.png", (50, 50))
    jsonl = tmp_path / "data.jsonl"
    rows = [
        {"external_id": "x", "query": "q1", "image": img.name},
        {"external_id": "x", "query": "q2", "image": img.name},
    ]
    jsonl.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = import_file(db, cfg, jsonl)

    assert result.imported == 1
    assert result.rejected == 1
    assert "duplicate" in result.report[0]["error"]


def test_import_requires_rows(db, cfg, tmp_path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("external_id,query,image\n", encoding="utf-8")
    try:
        import_file(db, cfg, empty)
    except ValueError as exc:
        assert "no rows" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_storage.py tests/test_import.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.storage'`

- [ ] **Step 3: 实现存储工具**

`src/imageeval/storage.py`：

```python
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from .config import AppConfig


def ensure_data_dirs(cfg: AppConfig) -> None:
    for path in (
        cfg.data_dir,
        cfg.images_dir,
        cfg.thumbs_dir,
        cfg.exports_dir,
        cfg.reports_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def resolve_under(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes root: {relative}")
    return target


def validate_image(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.size
    except Exception as exc:
        raise ValueError(f"invalid image: {path.name}") from exc


def make_thumbnail(src: Path, dst: Path, max_edge: int = 480) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge))
        im.save(dst, format="JPEG", quality=85)


def downscale_bytes(path: Path, max_edge: int) -> tuple[bytes, str]:
    with Image.open(path) as im:
        has_alpha = im.mode in ("RGBA", "LA") or (
            im.mode == "P" and "transparency" in im.info
        )
        im.thumbnail((max_edge, max_edge))
        buffer = io.BytesIO()
        if has_alpha:
            im.convert("RGBA").save(buffer, format="PNG")
            return buffer.getvalue(), "image/png"
        im.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue(), "image/jpeg"


def image_data_url(path: Path, max_edge: int) -> str:
    data, mime = downscale_bytes(path, max_edge)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
```

- [ ] **Step 4: 实现导入服务**

`src/imageeval/importer.py`：

```python
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

from .config import AppConfig
from .db import Database
from .storage import ensure_data_dirs, make_thumbnail, validate_image

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass
class ImportResult:
    batch_id: str
    imported: int
    rejected: int
    report: list[dict]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row_no, row in enumerate(csv.DictReader(fh), start=2):
                yield row_no, dict(row)
        return
    if suffix in (".jsonl", ".ndjson"):
        for row_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("row must be a JSON object")
                yield row_no, row
            except Exception as exc:
                yield row_no, {"__error__": str(exc)}
        return
    raise ValueError(f"unsupported file type: {path.suffix}")


def _parse_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace("，", ";").split(";") if part.strip()]


def _parse_metadata(value: Any) -> dict:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return parsed


def _safe_suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix if suffix in ALLOWED_SUFFIXES else ".png"


def _prepare_image(
    image: str,
    batch_id: str,
    cfg: AppConfig,
    base_dir: Path,
    download: bool,
) -> Path:
    target_dir = cfg.images_dir / batch_id
    target_dir.mkdir(parents=True, exist_ok=True)

    if image.startswith(("http://", "https://")):
        if not download:
            raise ValueError("URL image requires download=true")
        response = httpx.get(image, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        content = response.content
        suffix = _safe_suffix(urlparse(image).path)
    else:
        source = Path(image)
        if not source.is_absolute():
            source = base_dir / source
        source = source.expanduser().resolve()
        if not source.exists():
            raise ValueError(f"image not found: {image}")
        content = source.read_bytes()
        suffix = _safe_suffix(source.name)

    digest = hashlib.sha256(content).hexdigest()[:12]
    destination = target_dir / f"{digest}{suffix}"
    if not destination.exists():
        destination.write_bytes(content)
    validate_image(destination)
    return destination


def import_file(
    db: Database,
    cfg: AppConfig,
    source_path: Path,
    image_root: Path | None = None,
    download: bool = False,
) -> ImportResult:
    ensure_data_dirs(cfg)
    source_path = Path(source_path)
    batch_id = str(uuid.uuid4())
    base_dir = Path(image_root).expanduser().resolve() if image_root else source_path.parent.resolve()
    now = utcnow()

    db.execute(
        "INSERT INTO import_batches (id, source_name, created_at, sample_count, rejected_count, report_json) "
        "VALUES (?, ?, ?, 0, 0, '[]')",
        (batch_id, source_path.name, now),
    )

    imported = 0
    rejected = 0
    report: list[dict] = []
    seen: set[str] = set()

    try:
        rows = list(_iter_rows(source_path))
    except ValueError:
        db.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
        raise

    for row_no, row in rows:
        try:
            if "__error__" in row:
                raise ValueError(row["__error__"])
            external_id = str(row.get("external_id") or "").strip()
            query = str(row.get("query") or "").strip()
            image = str(row.get("image") or "").strip()
            if not external_id:
                raise ValueError("external_id is required")
            if external_id in seen:
                raise ValueError(f"duplicate external_id: {external_id}")
            if not query:
                raise ValueError("query is required")
            if not image:
                raise ValueError("image is required")

            destination = _prepare_image(image, batch_id, cfg, base_dir, download)
            width, height = validate_image(destination)
            image_rel = destination.relative_to(cfg.images_dir).as_posix()
            thumb_rel = f"{batch_id}/{destination.stem}.jpg"
            make_thumbnail(destination, cfg.thumbs_dir / thumb_rel)

            db.execute(
                "INSERT INTO samples (id, batch_id, external_id, query_text, image_path, thumb_path, "
                "ref_image_path, model_name, width, height, tags_json, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    batch_id,
                    external_id,
                    query,
                    image_rel,
                    thumb_rel,
                    str(row.get("ref_image") or "").strip() or None,
                    str(row.get("model_name") or "").strip() or None,
                    width,
                    height,
                    json.dumps(_parse_tags(row.get("tags")), ensure_ascii=False),
                    json.dumps(_parse_metadata(row.get("metadata")), ensure_ascii=False),
                    now,
                ),
            )
            seen.add(external_id)
            imported += 1
        except Exception as exc:
            rejected += 1
            report.append(
                {
                    "row": row_no,
                    "external_id": str(row.get("external_id") or ""),
                    "error": str(exc),
                }
            )

    if imported == 0 and rejected == 0:
        db.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
        raise ValueError("no rows found in file")

    db.execute(
        "UPDATE import_batches SET sample_count = ?, rejected_count = ?, report_json = ? WHERE id = ?",
        (imported, rejected, json.dumps(report, ensure_ascii=False), batch_id),
    )
    return ImportResult(batch_id=batch_id, imported=imported, rejected=rejected, report=report)
```

- [ ] **Step 5: 添加 CLI 的 `import` 子命令**

`src/imageeval/__main__.py`：

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .db import Database, migrate
from .importer import import_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="imageeval")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="导入 CSV/JSONL")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument("--image-root", type=Path, default=None)
    import_parser.add_argument("--download", action="store_true")

    args = parser.parse_args(argv)
    cfg = load_config(args.config, args.data_dir)

    if args.command == "import":
        db = Database(cfg.db_path)
        migrate(db.conn)
        result = import_file(db, cfg, args.file, args.image_root, args.download)
        print(
            json.dumps(
                {
                    "batch_id": result.batch_id,
                    "imported": result.imported,
                    "rejected": result.rejected,
                    "report": result.report,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        db.close()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_storage.py tests/test_import.py -v`
Expected: `8 passed`

- [ ] **Step 7: 提交**

```bash
git add src/imageeval/storage.py src/imageeval/importer.py src/imageeval/__main__.py tests/test_storage.py tests/test_import.py
git commit -m "feat: 图片存储安全与 CSV/JSONL 导入"
```

---

## Task 6: Judge 协议与 Fake Provider

**Files:**
- Create: `src/imageeval/judge/__init__.py`
- Create: `src/imageeval/judge/base.py`
- Create: `src/imageeval/judge/fake.py`
- Create: `src/imageeval/util.py`
- Test: `tests/test_fake_provider.py`

**Interfaces:**
- Consumes: `JudgeOutput`、`SubScore`、`Requirement`（Task 3）、`AppConfig`/`JudgeConfig`（Task 1）
- Produces:
  - `JudgeResponse(raw, parsed, tokens_in, tokens_out, latency_ms, parse_attempts)`
  - 异常：`JudgeError`、`RetryableJudgeError`、`FatalJudgeError`、`SchemaJudgeError`
  - `JudgeProvider` Protocol：`name`、`model`、`async evaluate(query: str, image_path: Path) -> JudgeResponse`
  - `FakeProvider(model="fake-v1", adherence=4, quality=4, aesthetics=4, fail_times=0)`，属性 `calls`
  - `build_provider(cfg: AppConfig, rubric: Rubric) -> JudgeProvider`
  - `util.utcnow() -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_fake_provider.py`：

```python
import pytest

from imageeval.judge.base import RetryableJudgeError
from imageeval.judge.fake import FakeProvider


async def test_fake_provider_returns_valid_output(make_image) -> None:
    provider = FakeProvider(adherence=4, quality=4, aesthetics=4)
    response = await provider.evaluate("一只红色的猫", make_image())

    assert provider.calls == 1
    assert response.parsed.intent_alignment == 4
    assert response.parsed.requirements[0].criticality == "critical"
    assert response.parsed.subscores.quality.text_render.na is True
    assert response.tokens_in > 0
    assert response.parse_attempts == 1


async def test_fake_provider_fail_times(make_image) -> None:
    provider = FakeProvider(fail_times=1)
    with pytest.raises(RetryableJudgeError):
        await provider.evaluate("q", make_image())
    response = await provider.evaluate("q", make_image())
    assert response.parsed.verdict.startswith("fake")
    assert provider.calls == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_fake_provider.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.judge'`

- [ ] **Step 3: 实现工具、协议与 Fake Provider**

`src/imageeval/util.py`：

```python
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
```

`src/imageeval/judge/base.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import JudgeOutput


@dataclass(frozen=True)
class JudgeResponse:
    raw: str
    parsed: JudgeOutput
    tokens_in: int
    tokens_out: int
    latency_ms: int
    parse_attempts: int = 1


class JudgeError(Exception):
    """裁判调用失败的基类。"""


class RetryableJudgeError(JudgeError):
    """可重试：超时、429、5xx、网络错误。"""


class FatalJudgeError(JudgeError):
    """不可重试：4xx（429 除外）、响应非 JSON。"""


class SchemaJudgeError(JudgeError):
    """输出无法通过 schema 校验（已尝试修复一次）。"""


class JudgeProvider(Protocol):
    name: str
    model: str

    async def evaluate(self, query: str, image_path: Path) -> JudgeResponse: ...
```

`src/imageeval/judge/fake.py`：

```python
from __future__ import annotations

import json
import time
from pathlib import Path

from ..models import (
    AestheticSubscores,
    JudgeOutput,
    QualitySubscores,
    Requirement,
    SubScore,
    Subscores,
)
from .base import JudgeResponse, RetryableJudgeError


def _sub(score: int) -> SubScore:
    return SubScore(score=score, reason="fake")


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        model: str = "fake-v1",
        adherence: int = 4,
        quality: int = 4,
        aesthetics: int = 4,
        fail_times: int = 0,
    ):
        self.model = model
        self._adherence = adherence
        self._quality = quality
        self._aesthetics = aesthetics
        self._remaining_failures = fail_times
        self.calls = 0

    async def evaluate(self, query: str, image_path: Path) -> JudgeResponse:
        self.calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RetryableJudgeError("fake transient failure")

        started = time.perf_counter()
        output = JudgeOutput(
            observation=f"fake observation for {image_path.name}",
            requirements=[
                Requirement(
                    text=query,
                    category="subject",
                    criticality="critical",
                    status="satisfied",
                    evidence="fake evidence",
                ),
                Requirement(
                    text="风格一致",
                    category="style",
                    criticality="normal",
                    status="satisfied",
                    evidence="fake evidence",
                ),
            ],
            intent_alignment=self._adherence,
            subscores=Subscores(
                quality=QualitySubscores(
                    clarity=_sub(self._quality),
                    artifacts=_sub(self._quality),
                    text_render=SubScore(score=None, reason="fake no text", na=True),
                    physics=_sub(self._quality),
                    consistency=_sub(self._quality),
                ),
                aesthetics=AestheticSubscores(
                    composition=_sub(self._aesthetics),
                    color=_sub(self._aesthetics),
                    lighting=_sub(self._aesthetics),
                    texture=_sub(self._aesthetics),
                    appeal=_sub(self._aesthetics),
                ),
            ),
            notable_issues=[],
            verdict="fake verdict",
        )
        raw = json.dumps(output.model_dump(), ensure_ascii=False)
        return JudgeResponse(
            raw=raw,
            parsed=output,
            tokens_in=100,
            tokens_out=100,
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
            parse_attempts=1,
        )
```

`src/imageeval/judge/__init__.py`：

```python
from __future__ import annotations

from ..config import AppConfig
from ..rubric.loader import Rubric
from .base import JudgeProvider


def build_provider(cfg: AppConfig, rubric: Rubric) -> JudgeProvider:
    if cfg.judge.provider == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    from .openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(cfg.judge, rubric)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_fake_provider.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add src/imageeval/util.py src/imageeval/judge tests/test_fake_provider.py
git commit -m "feat: Judge 协议、异常与 Fake Provider"
```

---

## Task 7: 提示词与 OpenAI 兼容 Provider

**Files:**
- Create: `src/imageeval/judge/prompts.py`
- Create: `src/imageeval/judge/openai_compat.py`
- Create: `tests/helpers.py`
- Test: `tests/test_prompts.py`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: `JudgeConfig`、`Rubric`、`JudgeResponse`、异常、`parse_judge_output`、`image_data_url`
- Produces:
  - `PROMPT_VERSION`
  - `prompt_hash(rubric: Rubric) -> str`（16 位）
  - `build_messages(query: str, image_data_url: str, rubric: Rubric) -> list[dict]`
  - `OpenAICompatProvider(cfg: JudgeConfig, rubric: Rubric, client: httpx.AsyncClient | None = None)`，方法 `async evaluate(...)`、`async aclose()`
  - `tests/helpers.py::valid_judge_payload(score=4) -> dict`

- [ ] **Step 1: 写失败测试**

`tests/helpers.py`：

```python
from __future__ import annotations


def valid_judge_payload(score: int = 4) -> dict:
    def sub(value: int) -> dict:
        return {"score": value, "reason": "理由"}

    return {
        "observation": "画面中有一只红色的猫。",
        "requirements": [
            {
                "text": "红色的猫",
                "category": "subject",
                "criticality": "critical",
                "status": "satisfied",
                "evidence": "画面中央的猫为红色",
            }
        ],
        "intent_alignment": score,
        "subscores": {
            "quality": {
                "clarity": sub(score),
                "artifacts": sub(score),
                "text_render": {"score": None, "reason": "无文字", "na": True},
                "physics": sub(score),
                "consistency": sub(score),
            },
            "aesthetics": {
                "composition": sub(score),
                "color": sub(score),
                "lighting": sub(score),
                "texture": sub(score),
                "appeal": sub(score),
            },
        },
        "notable_issues": [],
        "verdict": "整体符合要求",
    }
```

`tests/test_prompts.py`：

```python
from imageeval.judge.prompts import build_messages, prompt_hash


def test_prompt_hash_is_stable(rubric) -> None:
    first = prompt_hash(rubric)
    assert first == prompt_hash(rubric)
    assert len(first) == 16


def test_messages_contain_query_image_and_anchors(rubric) -> None:
    messages = build_messages("一只红色的猫", "data:image/png;base64,AAA", rubric)
    assert messages[0]["role"] == "system"
    assert "1 = 严重问题" in messages[0]["content"]
    assert "至少一条必须是 critical" in messages[0]["content"]

    user_parts = messages[1]["content"]
    assert user_parts[0]["type"] == "text"
    assert "一只红色的猫" in user_parts[0]["text"]
    assert user_parts[1]["image_url"]["url"] == "data:image/png;base64,AAA"
```

`tests/test_provider.py`：

```python
import json

import httpx
import pytest

from imageeval.config import JudgeConfig
from imageeval.judge.base import (
    FatalJudgeError,
    RetryableJudgeError,
    SchemaJudgeError,
)
from imageeval.judge.openai_compat import OpenAICompatProvider
from tests.helpers import valid_judge_payload


def _provider(handler, rubric, **kwargs) -> OpenAICompatProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = JudgeConfig(base_url="http://judge.test/v1", model="vision-test", **kwargs)
    return OpenAICompatProvider(cfg, rubric, client=client)


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps(valid_judge_payload(), ensure_ascii=False)}}
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22},
        },
    )


async def test_success_returns_parsed_and_usage(rubric, make_image) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok_response()

    provider = _provider(handler, rubric)
    response = await provider.evaluate("一只红色的猫", make_image())

    assert response.parsed.intent_alignment == 4
    assert response.tokens_in == 11
    assert response.tokens_out == 22
    assert response.parse_attempts == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == "vision-test"
    assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/")


async def test_429_is_retryable(rubric, make_image) -> None:
    provider = _provider(lambda request: httpx.Response(429, json={"error": "rate"}), rubric)
    with pytest.raises(RetryableJudgeError):
        await provider.evaluate("q", make_image())


async def test_400_is_fatal(rubric, make_image) -> None:
    provider = _provider(lambda request: httpx.Response(400, json={"error": "bad"}), rubric)
    with pytest.raises(FatalJudgeError):
        await provider.evaluate("q", make_image())


async def test_schema_error_repairs_once_then_fails(rubric, make_image) -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    provider = _provider(handler, rubric)
    with pytest.raises(SchemaJudgeError):
        await provider.evaluate("q", make_image())

    assert len(bodies) == 2
    assert "输出不合法" in bodies[1]["messages"][-1]["content"]


async def test_schema_error_then_success(rubric, make_image) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "oops"}}]})
        return _ok_response()

    provider = _provider(handler, rubric)
    response = await provider.evaluate("q", make_image())
    assert response.parse_attempts == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_prompts.py tests/test_provider.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.judge.prompts'`

- [ ] **Step 3: 实现提示词**

`src/imageeval/judge/prompts.py`：

```python
from __future__ import annotations

import hashlib

from ..rubric.loader import Rubric

PROMPT_VERSION = "p1"

SYSTEM_TEMPLATE = """你是严格的文生图质量评测专家。你的任务是依据给定评分标准，评估「原始 Query」与「生成图片」的匹配程度。

评分尺度（1-5 整数）：
{anchors}

必须遵守的流程：
1. 先写 observation：客观描述画面里实际有什么（人物、物体、数量、颜色、文字、空间关系、风格）。不要评价，只描述。
2. 把 Query 拆成原子需求 requirements，每条包含：
   - text：需求内容
   - category：subject / attribute / count / relation / style / text_render / negative
   - criticality：critical（主体、数量、明确否定约束等，不满足则任务失败）或 normal
   - status：satisfied / partial / missing / contradicted
   - evidence：图中支持该判定的具体位置或内容
   requirements 不得为空，且至少一条必须是 critical。
   negative 需求表示「不要出现 X」，status=satisfied 表示图中没有出现 X。
3. 给出 intent_alignment（1-5 整数）：整体意图是否贴合 Query，即使细节有出入。
4. 给视觉质量子项打分：clarity / artifacts / text_render / physics / consistency。
   若 Query 没有文字要求且画面不需要文字，text_render 的 score 设为 null、na 设为 true。
5. 给美学子项打分：composition / color / lighting / texture / appeal。
6. 所有子项都必须给出 reason（简短中文）。
7. 输出必须是一个 JSON 对象，不要输出 Markdown 代码块，不要输出任何 JSON 之外的文字。

JSON 结构（字段名与层级必须完全一致）：
{{
  "observation": "画面客观描述",
  "requirements": [
    {{"text": "红色雨伞", "category": "attribute", "criticality": "critical",
      "status": "satisfied", "evidence": "画面中央偏左有一把红色雨伞"}}
  ],
  "intent_alignment": 4,
  "subscores": {{
    "quality": {{
      "clarity": {{"score": 4, "reason": "清晰度良好"}},
      "artifacts": {{"score": 3, "reason": "左手手指数量异常"}},
      "text_render": {{"score": null, "reason": "画面无文字要求", "na": true}},
      "physics": {{"score": 4, "reason": "透视与光影合理"}},
      "consistency": {{"score": 4, "reason": "风格统一"}}
    }},
    "aesthetics": {{
      "composition": {{"score": 4, "reason": "构图稳定"}},
      "color": {{"score": 5, "reason": "配色和谐"}},
      "lighting": {{"score": 4, "reason": "光线自然"}},
      "texture": {{"score": 3, "reason": "质感一般"}},
      "appeal": {{"score": 4, "reason": "整体有吸引力"}}
    }}
  }},
  "notable_issues": ["左手手指异常"],
  "verdict": "一句话结论"
}}"""


def _anchors_text(rubric: Rubric) -> str:
    return "\n".join(f"{score} = {text}" for score, text in sorted(rubric.anchors.items()))


def prompt_hash(rubric: Rubric) -> str:
    material = f"{PROMPT_VERSION}|{rubric.version}|{SYSTEM_TEMPLATE}|{_anchors_text(rubric)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_messages(query: str, image_data_url: str, rubric: Rubric) -> list[dict]:
    system = SYSTEM_TEMPLATE.format(anchors=_anchors_text(rubric))
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"原始 Query：\n{query}"},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]
```

- [ ] **Step 4: 实现 OpenAI 兼容 Provider**

`src/imageeval/judge/openai_compat.py`：

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from ..config import JudgeConfig
from ..models import parse_judge_output
from ..rubric.loader import Rubric
from ..storage import image_data_url
from .base import (
    FatalJudgeError,
    JudgeResponse,
    RetryableJudgeError,
    SchemaJudgeError,
)
from .prompts import build_messages


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        cfg: JudgeConfig,
        rubric: Rubric,
        client: httpx.AsyncClient | None = None,
    ):
        self._cfg = cfg
        self._rubric = rubric
        self.model = cfg.model
        self._client = client or httpx.AsyncClient(timeout=cfg.timeout_s)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post(self, messages: list[dict]) -> tuple[str, dict]:
        headers = {"Content-Type": "application/json"}
        import os

        api_key = os.environ.get(self._cfg.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
            "max_tokens": self._cfg.max_tokens,
        }
        try:
            response = await self._client.post(
                f"{self._cfg.base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise RetryableJudgeError(f"timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableJudgeError(f"transport error: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableJudgeError(f"http {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise FatalJudgeError(f"http {response.status_code}: {response.text[:200]}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise FatalJudgeError(f"malformed response envelope: {exc}") from exc

        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str):
            raise FatalJudgeError("response content is not text")
        return content, data.get("usage") or {}

    async def evaluate(self, query: str, image_path: Path) -> JudgeResponse:
        started = time.perf_counter()
        data_url = image_data_url(image_path, self._cfg.image_max_edge)
        messages = build_messages(query, data_url, self._rubric)
        last_error: Exception | None = None

        for attempt in (1, 2):
            content, usage = await self._post(messages)
            try:
                parsed = parse_judge_output(content)
                return JudgeResponse(
                    raw=content,
                    parsed=parsed,
                    tokens_in=int(usage.get("prompt_tokens", 0)),
                    tokens_out=int(usage.get("completion_tokens", 0)),
                    latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
                    parse_attempts=attempt,
                )
            except Exception as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"输出不合法：{exc}。只输出符合 schema 的 JSON 对象，不要输出其他文字。",
                    },
                ]

        raise SchemaJudgeError(f"invalid judge output after repair: {last_error}")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_prompts.py tests/test_provider.py -v`
Expected: `7 passed`

- [ ] **Step 6: 提交**

```bash
git add src/imageeval/judge/prompts.py src/imageeval/judge/openai_compat.py tests/helpers.py tests/test_prompts.py tests/test_provider.py
git commit -m "feat: 评测提示词与 OpenAI 兼容多模态 Provider"
```

---

## Task 8: 评分流水线与 Run 管理

**Files:**
- Create: `src/imageeval/runs.py`
- Create: `src/imageeval/pipeline.py`
- Modify: `src/imageeval/__main__.py`（新增 `run` 子命令）
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Database`、`AppConfig`、`Rubric`、`JudgeProvider`、`compute_scores`、`resolve_under`、`utcnow`
- Produces:
  - `create_run(db, cfg, rubric, batch_id, name) -> str`
  - `get_run(db, run_id) -> dict`
  - `list_runs(db, batch_id=None) -> list[dict]`
  - `RunControl(paused: bool, cancelled: bool)`
  - `execute_run(db, cfg, provider, rubric, run_id, control=None) -> None`
  - `RunManager(db, cfg, provider, rubric)`：`.start(run_id) -> bool`、`.pause(run_id)`、`.cancel(run_id)`、`.is_running(run_id) -> bool`
  - CLI：`python -m imageeval run (--run-id ID | --new --batch-id BATCH)`

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.pipeline'`

- [ ] **Step 3: 实现 runs 与流水线**

`src/imageeval/runs.py`：

```python
from __future__ import annotations

import json
import uuid

from .config import AppConfig
from .db import Database
from .judge.prompts import prompt_hash
from .rubric.loader import Rubric
from .util import utcnow


def create_run(
    db: Database, cfg: AppConfig, rubric: Rubric, batch_id: str, name: str
) -> str:
    batch = db.query_one("SELECT id FROM import_batches WHERE id = ?", (batch_id,))
    if batch is None:
        raise ValueError(f"batch not found: {batch_id}")
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM samples WHERE batch_id = ?", (batch_id,)
    )["c"]
    run_id = str(uuid.uuid4())
    params = {
        "temperature": cfg.judge.temperature,
        "image_max_edge": cfg.judge.image_max_edge,
        "max_concurrency": cfg.pipeline.max_concurrency,
        "rpm": cfg.pipeline.rpm,
        "max_retries": cfg.pipeline.max_retries,
    }
    db.execute(
        "INSERT INTO runs (id, name, batch_id, rubric_version, prompt_hash, provider, "
        "judge_model, params_json, status, total, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (
            run_id,
            name,
            batch_id,
            rubric.version,
            prompt_hash(rubric),
            cfg.judge.provider,
            cfg.judge.model,
            json.dumps(params, ensure_ascii=False),
            total,
            utcnow(),
        ),
    )
    return run_id


def get_run(db: Database, run_id: str) -> dict:
    row = db.query_one(
        "SELECT r.*, b.source_name FROM runs r "
        "JOIN import_batches b ON b.id = r.batch_id WHERE r.id = ?",
        (run_id,),
    )
    if row is None:
        raise LookupError(f"run not found: {run_id}")
    return dict(row)


def list_runs(db: Database, batch_id: str | None = None) -> list[dict]:
    if batch_id:
        rows = db.query(
            "SELECT * FROM runs WHERE batch_id = ? ORDER BY created_at DESC", (batch_id,)
        )
    else:
        rows = db.query("SELECT * FROM runs ORDER BY created_at DESC")
    return [dict(row) for row in rows]
```

`src/imageeval/pipeline.py`：

```python
from __future__ import annotations

import asyncio
import json
import random
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
    image_path = resolve_under(cfg.images_dir, sample["image_path"])
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
            await _evaluate_one(db, cfg, provider, rubric, run_id, sample)
            _refresh_counts(db, run_id)

    workers = [
        asyncio.create_task(worker())
        for _ in range(max(1, cfg.pipeline.max_concurrency))
    ]
    await asyncio.gather(*workers, return_exceptions=True)

    usage = db.query_one(
        "SELECT COALESCE(SUM(tokens_in), 0) AS ti, COALESCE(SUM(tokens_out), 0) AS to_, "
        "COALESCE(SUM(latency_ms), 0) AS lm FROM evaluations WHERE run_id = ?",
        (run_id,),
    )
    status = "cancelled" if control.cancelled else "completed"
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
            return False
        control = RunControl()
        self._controls[run_id] = control
        task = asyncio.create_task(
            execute_run(
                self._db, self._cfg, self._provider, self._rubric, run_id, control
            )
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
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
```

- [ ] **Step 4: 添加 CLI `run` 子命令**

在 `src/imageeval/__main__.py` 中，`import_parser` 之后追加：

```python
    run_parser = subparsers.add_parser("run", help="执行一次评测")
    group = run_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", default=None)
    group.add_argument("--new", action="store_true")
    run_parser.add_argument("--batch-id", default=None)
    run_parser.add_argument("--name", default="CLI run")
```

在 `if args.command == "import":` 之前追加：

```python
    import asyncio

    from .judge import build_provider
    from .pipeline import execute_run
    from .rubric.loader import load_rubric
    from .runs import create_run
```

在 `return 1` 之前追加：

```python
    if args.command == "run":
        db = Database(cfg.db_path)
        migrate(db.conn)
        rubric = load_rubric(cfg.rubric_path)
        if args.new:
            if not args.batch_id:
                parser.error("--new requires --batch-id")
            run_id = create_run(db, cfg, rubric, args.batch_id, args.name)
        else:
            run_id = args.run_id
        provider = build_provider(cfg, rubric)
        asyncio.run(execute_run(db, cfg, provider, rubric, run_id))
        run = db.query_one("SELECT status, done, failed, total FROM runs WHERE id = ?", (run_id,))
        print(json.dumps(dict(run), ensure_ascii=False))
        db.close()
        return 0
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: `4 passed`（含退避等待，约 1–2 秒）

- [ ] **Step 6: 提交**

```bash
git add src/imageeval/runs.py src/imageeval/pipeline.py src/imageeval/__main__.py tests/test_pipeline.py
git commit -m "feat: 异步评分流水线、重试与断点续跑"
```

---

## Task 9: 复核服务

**Files:**
- Create: `src/imageeval/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `Database`、`AppConfig`、`Rubric`、`ReviewSubmit`、`compute_overall`、`utcnow`
- Produces:
  - `QUEUE_FILTERS`、`QUEUE_ORDERS`
  - `review_queue(db, run_id, filter_name="pending", order="default", limit=50, offset=0) -> dict`
  - `submit_review(db, cfg, rubric, evaluation_id, payload: ReviewSubmit, reviewer: str | None = None) -> dict`
  - `counts(db, run_id) -> dict{"total", "by_state"}`

- [ ] **Step 1: 写失败测试**

`tests/test_review.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_review.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.review'`

- [ ] **Step 3: 实现复核服务**

`src/imageeval/review.py`：

```python
from __future__ import annotations

import json
import uuid

from .config import AppConfig
from .db import Database
from .models import ReviewSubmit
from .rubric.loader import Rubric
from .scoring import compute_overall
from .util import utcnow

QUEUE_FILTERS = {
    "pending": "st.state = 'ai_done'",
    "reviewed": "st.state IN ('accepted', 'corrected')",
    "skipped": "st.state = 'skipped'",
    "all": "1 = 1",
}

QUEUE_ORDERS = {
    "default": "s.created_at ASC",
    "low_ai": "e.overall_score IS NULL, e.overall_score ASC",
    "max_correction": "correction DESC",
    "random": "RANDOM()",
}

_BASE_FROM = """
FROM runs rn
JOIN samples s ON s.batch_id = rn.batch_id
JOIN evaluations e ON e.sample_id = s.id AND e.run_id = rn.id
JOIN v_evaluation_state st ON st.id = e.id
LEFT JOIN reviews r ON r.id = (
    SELECT id FROM reviews WHERE evaluation_id = e.id
    ORDER BY created_at DESC, id DESC LIMIT 1
)
"""

_SELECT = """
SELECT s.id AS sample_id, s.query_text, s.image_path, s.thumb_path, s.model_name, s.tags_json,
       e.id AS evaluation_id, e.status AS eval_status,
       e.adherence_score, e.quality_score, e.aesthetics_score, e.overall_score,
       e.requirements_json, e.subscores_json, e.observation, e.verdict,
       st.state,
       r.id AS review_id, r.decision, r.human_adherence, r.human_quality,
       r.human_aesthetics, r.human_overall, r.note AS review_note,
       r.reasons_json, r.created_at AS reviewed_at,
       (COALESCE(ABS(r.human_adherence - e.adherence_score), 0)
        + COALESCE(ABS(r.human_quality - e.quality_score), 0)
        + COALESCE(ABS(r.human_aesthetics - e.aesthetics_score), 0)) AS correction
"""


def _row_to_item(row) -> dict:
    human = None
    if row["review_id"] is not None:
        human = {
            "decision": row["decision"],
            "adherence": row["human_adherence"],
            "quality": row["human_quality"],
            "aesthetics": row["human_aesthetics"],
            "overall": row["human_overall"],
            "reasons": json.loads(row["reasons_json"] or "{}"),
            "note": row["review_note"] or "",
            "reviewed_at": row["reviewed_at"],
        }
    return {
        "sample_id": row["sample_id"],
        "evaluation_id": row["evaluation_id"],
        "state": row["state"],
        "query": row["query_text"],
        "image_url": f"/api/samples/{row['sample_id']}/image?size=orig",
        "thumb_url": f"/api/samples/{row['sample_id']}/image?size=thumb",
        "model_name": row["model_name"],
        "tags": json.loads(row["tags_json"] or "[]"),
        "ai": {
            "adherence": row["adherence_score"],
            "quality": row["quality_score"],
            "aesthetics": row["aesthetics_score"],
            "overall": row["overall_score"],
            "requirements": json.loads(row["requirements_json"] or "[]"),
            "subscores": json.loads(row["subscores_json"] or "{}"),
            "observation": row["observation"],
            "verdict": row["verdict"],
        },
        "human": human,
    }


def review_queue(
    db: Database,
    run_id: str,
    filter_name: str = "pending",
    order: str = "default",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if filter_name not in QUEUE_FILTERS:
        raise ValueError(f"unknown filter: {filter_name}")
    if order not in QUEUE_ORDERS:
        raise ValueError(f"unknown order: {order}")

    where = f"WHERE rn.id = ? AND {QUEUE_FILTERS[filter_name]}"
    total = db.query_one(f"SELECT COUNT(*) AS c {_BASE_FROM} {where}", (run_id,))["c"]
    rows = db.query(
        f"{_SELECT} {_BASE_FROM} {where} ORDER BY {QUEUE_ORDERS[order]} LIMIT ? OFFSET ?",
        (run_id, limit, offset),
    )
    return {"total": total, "items": [_row_to_item(row) for row in rows]}


def submit_review(
    db: Database,
    cfg: AppConfig,
    rubric: Rubric,
    evaluation_id: str,
    payload: ReviewSubmit,
    reviewer: str | None = None,
) -> dict:
    row = db.query_one("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,))
    if row is None:
        raise LookupError(f"evaluation not found: {evaluation_id}")
    if row["status"] != "ok":
        raise ValueError("cannot review a failed evaluation")

    adherence = quality = aesthetics = None
    if payload.decision == "accepted":
        adherence = payload.human_adherence or int(round(row["adherence_score"]))
        quality = payload.human_quality or int(round(row["quality_score"]))
        aesthetics = payload.human_aesthetics or int(round(row["aesthetics_score"]))
    elif payload.decision == "corrected":
        adherence = payload.human_adherence
        quality = payload.human_quality
        aesthetics = payload.human_aesthetics

    overall = (
        compute_overall(adherence, quality, aesthetics, rubric)
        if adherence is not None
        else None
    )
    review_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO reviews (id, evaluation_id, reviewer, decision, human_adherence, "
        "human_quality, human_aesthetics, human_overall, reasons_json, note, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            review_id,
            evaluation_id,
            reviewer or cfg.reviewer_name,
            payload.decision,
            adherence,
            quality,
            aesthetics,
            overall,
            json.dumps(payload.reasons, ensure_ascii=False),
            payload.note,
            payload.duration_ms,
            utcnow(),
        ),
    )
    return {
        "review_id": review_id,
        "decision": payload.decision,
        "human_adherence": adherence,
        "human_quality": quality,
        "human_aesthetics": aesthetics,
        "human_overall": overall,
    }


def counts(db: Database, run_id: str) -> dict:
    rows = db.query(
        "SELECT st.state AS state, COUNT(*) AS c FROM evaluations e "
        "JOIN v_evaluation_state st ON st.id = e.id WHERE e.run_id = ? GROUP BY st.state",
        (run_id,),
    )
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM samples s JOIN runs r ON r.batch_id = s.batch_id "
        "WHERE r.id = ?",
        (run_id,),
    )["c"]
    return {"total": total, "by_state": {row["state"]: row["c"] for row in rows}}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_review.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```bash
git add src/imageeval/review.py tests/test_review.py
git commit -m "feat: 复核队列、状态推导与 append-only 复核记录"
```

---

## Task 10: 报告统计与失败案例选择（含学习点）

**Files:**
- Create: `src/imageeval/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Database`、`Rubric`、`counts`（Task 9）
- Produces:
  - `build_summary(db, run_id, rubric) -> dict`
  - `select_failure_cases(rows: list[dict], top_n: int = 12) -> list[dict]`
  - 内部：`spearman(xs, ys)`、`mae(pairs)`
  - `summary` 结构：`run`、`counts`、`means`、`acceptance_rate`、`distributions`、`radar`、`agreement`、`attribution`、`failures`、`samples`

- [ ] **Step 1: 写失败测试**

`tests/test_report.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.report'`

- [ ] **Step 3: 实现统计（`select_failure_cases` 先留学习点占位）**

`src/imageeval/report.py`：

```python
from __future__ import annotations

import json
import math

from .db import Database
from .review import counts
from .rubric.loader import Rubric

DIMENSIONS = ("adherence", "quality", "aesthetics")


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
    # 学习点：由用户实现，参考实现见附录 A.2
    raise NotImplementedError


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

    state_counts = counts(db, run_id)["by_state"]
    summary_counts = {
        "total": counts(db, run_id)["total"],
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
```

- [ ] **Step 4（学习点，默认由用户完成）: 实现 `select_failure_cases`**

输入 `rows` 中每行包含：`human_overall`、`correction`（三维人工与 AI 绝对差之和）、三维人工分、三维 AI 分、`requirements`。

需要决定：什么算“失败案例”？低分阈值、修正幅度阈值、是否按需求缺失类型加权、排序规则。测试按默认策略编写（`human_overall <= 3.0` 或 `correction >= 1.5`，按人工总分升序、修正幅度降序）；若采用不同策略，先改测试期望。

**参考实现见附录 A.2；仅在用户明确委托时使用。**

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_report.py -v`
Expected: `6 passed`

- [ ] **Step 6: 提交**

```bash
git add src/imageeval/report.py tests/test_report.py
git commit -m "feat: 报告统计、需求归因与失败案例选择"
```

---

## Task 11: 报告渲染器与报告页

**Files:**
- Create: `src/imageeval/web/style.css`
- Create: `src/imageeval/web/report.html`
- Create: `src/imageeval/web/report.js`
- Create: `src/imageeval/web/vendor/chart.umd.js`（下载）
- Modify: `src/imageeval/report.py`（追加 `render_report_html`）
- Test: `tests/test_report_render.py`

**Interfaces:**
- Consumes: `build_summary` 输出、`resolve_under`、`WEB_DIR`
- Produces:
  - `WEB_DIR: Path`
  - `render_report_html(summary: dict, data_dir: Path, inline_images: bool = False) -> str`

- [ ] **Step 1: 下载 Chart.js**

```bash
mkdir -p src/imageeval/web/vendor
curl -L -o src/imageeval/web/vendor/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js
test -s src/imageeval/web/vendor/chart.umd.js && wc -c src/imageeval/web/vendor/chart.umd.js
```

Expected: 文件大于 100000 字节。若 CDN 不可用，改用 `https://unpkg.com/chart.js@4.4.7/dist/chart.umd.js`。

- [ ] **Step 2: 写失败测试**

`tests/test_report_render.py`：

```python
from imageeval.report import build_summary, render_report_html
from imageeval.review import submit_review
from imageeval.models import ReviewSubmit
from imageeval.runs import create_run


def test_render_report_html_inlines_assets(db, cfg, rubric, seed_batch) -> None:
    from tests.test_report import _add_eval

    batch_id, sample_ids = seed_batch(1)
    run_id = create_run(db, cfg, rubric, batch_id, "报告测试")
    eval_id = _add_eval(db, run_id, sample_ids[0], (4, 4, 4))
    submit_review(db, cfg, rubric, eval_id, ReviewSubmit(decision="accepted"))

    summary = build_summary(db, run_id, rubric)
    html = render_report_html(summary, cfg.data_dir)

    assert "报告测试" in html
    assert "window.__REPORT_DATA__" in html
    assert "Chart" in html
    assert "{{" not in html
    assert "<style>" in html
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_render.py -v`
Expected: FAIL，`ImportError: cannot import name 'render_report_html'`

- [ ] **Step 4: 创建样式与页面模板**

`src/imageeval/web/style.css`：

```css
:root {
  --bg: #0f1117;
  --panel: #171a23;
  --panel-2: #1e2230;
  --line: #2a3043;
  --text: #e6e9f2;
  --muted: #8b93a7;
  --accent: #7c9cff;
  --warn: #ffb86b;
  --ok: #4ecdc4;
  --bad: #ff6b81;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
}
a { color: var(--accent); }
button, select, input, textarea {
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
  font: inherit;
}
button { cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: #0b0d13; border-color: var(--accent); font-weight: 600; }
header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  flex-wrap: wrap;
}
main.review {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 420px;
  gap: 12px;
  padding: 12px;
  height: calc(100vh - 58px);
}
aside.filters, section.viewer, section.panel, .card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
}
aside.filters { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
aside.filters label { color: var(--muted); font-size: 12px; }
section.viewer { display: flex; flex-direction: column; overflow: hidden; }
#image-wrap { flex: 1; overflow: hidden; display: grid; place-items: center; cursor: grab; }
#image-wrap.dragging { cursor: grabbing; }
#image { max-width: 100%; max-height: 100%; transform-origin: center center; }
section.panel { padding: 14px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
section.panel h2 { font-size: 13px; color: var(--muted); margin: 8px 0 0; font-weight: 600; }
#query { font-size: 16px; line-height: 1.7; background: var(--panel-2); padding: 10px; border-radius: 8px; }
ul.requirements { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
ul.requirements li { padding: 8px; border-radius: 8px; background: var(--panel-2); border-left: 3px solid var(--muted); }
ul.requirements li.satisfied { border-left-color: var(--ok); }
ul.requirements li.partial { border-left-color: var(--warn); }
ul.requirements li.missing, ul.requirements li.contradicted { border-left-color: var(--bad); }
.req-meta { font-size: 11px; color: var(--muted); }
.score-row { display: grid; grid-template-columns: 1fr 90px; align-items: center; gap: 8px; }
.score-row.focused label { color: var(--accent); font-weight: 600; }
.score-row input { text-align: center; }
.actions { display: flex; gap: 8px; margin-top: auto; }
.actions button { flex: 1; }
.hint { color: var(--muted); font-size: 12px; }
.hidden { display: none !important; }
.modal {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6);
  display: grid; place-items: center; z-index: 20;
}
.modal .card { width: min(560px, 92vw); padding: 18px; display: flex; flex-direction: column; gap: 10px; }
.report { padding: 16px; max-width: 1280px; margin: 0 auto; }
.report h1 { font-size: 22px; margin: 4px 0 2px; }
.report h2 { font-size: 15px; margin: 20px 0 8px; }
.grid { display: grid; gap: 12px; }
.grid.cards { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.grid.charts { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.card { padding: 14px; }
.card .label { color: var(--muted); font-size: 12px; }
.card .value { font-size: 24px; font-weight: 700; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
th { color: var(--muted); font-weight: 600; }
.failure-wall { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.failure-wall .card { padding: 8px; }
.failure-wall img { width: 100%; border-radius: 8px; display: block; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 11px; background: var(--panel-2); border: 1px solid var(--line); }
```

`src/imageeval/web/report.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>{{CSS}}</style>
</head>
<body>
<div class="report">
  <h1 id="run-title">评测报告</h1>
  <div class="hint" id="run-meta"></div>

  <h2>概览</h2>
  <div class="grid cards" id="cards"></div>

  <h2>AI 与人工一致性</h2>
  <div class="grid cards" id="agreement-cards"></div>

  <h2>分布与雷达</h2>
  <div class="grid charts">
    <div class="card"><canvas id="chart-adherence"></canvas></div>
    <div class="card"><canvas id="chart-quality"></canvas></div>
    <div class="card"><canvas id="chart-aesthetics"></canvas></div>
    <div class="card"><canvas id="chart-radar"></canvas></div>
    <div class="card"><canvas id="chart-scatter"></canvas></div>
  </div>

  <h2>需求归因</h2>
  <div class="grid charts">
    <div class="card"><table id="table-attribution"></table></div>
    <div class="card"><div id="status-counts" class="hint"></div></div>
  </div>

  <h2>混淆矩阵（AI 分 vs 人工分）</h2>
  <div class="grid charts" id="confusion"></div>

  <h2>失败案例</h2>
  <div class="failure-wall" id="failure-wall"></div>

  <h2>已复核明细</h2>
  <div class="card"><table id="sample-table"></table></div>
</div>
<script>{{CHART_JS}}</script>
<script>window.__REPORT_DATA__ = {{DATA_JSON}};</script>
<script>{{REPORT_JS}}</script>
</body>
</html>
```

`src/imageeval/web/report.js`：

```js
(function () {
  const data = window.__REPORT_DATA__;
  if (!data) return;
  const dims = ["adherence", "quality", "aesthetics"];
  const dimNames = { adherence: "需求遵循", quality: "视觉质量", aesthetics: "美学" };
  const colors = { adherence: "#7c9cff", quality: "#4ecdc4", aesthetics: "#ffb86b" };

  const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%");

  document.getElementById("run-title").textContent = data.run.name || "评测报告";
  document.getElementById("run-meta").textContent =
    `${data.run.rubric_version} · ${data.run.judge_model} · ${data.counts.total} 张`;

  const cards = [
    ["样本数", data.counts.total],
    ["已评分", data.counts.ok],
    ["AI 待复核", data.counts.ai_done],
    ["已复核", data.counts.reviewed],
    ["错误", data.counts.error],
    ["人工接受率", pct(data.acceptance_rate)],
  ];
  document.getElementById("cards").innerHTML = cards
    .map(([label, value]) => `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`)
    .join("");

  const agreementCards = [];
  for (const dim of dims) {
    agreementCards.push(`<div class="card"><div class="label">${dimNames[dim]} MAE</div><div class="value">${fmt(data.agreement.mae[dim])}</div></div>`);
    agreementCards.push(`<div class="card"><div class="label">${dimNames[dim]} Spearman</div><div class="value">${fmt(data.agreement.spearman[dim])}</div></div>`);
  }
  agreementCards.push(`<div class="card"><div class="label">已复核样本</div><div class="value">${data.agreement.n}</div></div>`);
  document.getElementById("agreement-cards").innerHTML = agreementCards.join("");

  for (const dim of dims) {
    new Chart(document.getElementById(`chart-${dim}`), {
      type: "bar",
      data: {
        labels: ["1", "2", "3", "4", "5"],
        datasets: [
          { label: "AI", data: data.distributions[dim].ai, backgroundColor: colors[dim] },
          { label: "人工", data: data.distributions[dim].human, backgroundColor: "#8b93a7" },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: `${dimNames[dim]}分布` },
          legend: { position: "bottom" },
        },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }

  new Chart(document.getElementById("chart-radar"), {
    type: "radar",
    data: {
      labels: data.radar.labels,
      datasets: [
        { label: "AI", data: data.radar.ai, borderColor: "#7c9cff", backgroundColor: "rgba(124,156,255,.2)" },
        { label: "人工", data: data.radar.human, borderColor: "#ffb86b", backgroundColor: "rgba(255,184,107,.2)" },
      ],
    },
    options: { scales: { r: { min: 1, max: 5 } } },
  });

  new Chart(document.getElementById("chart-scatter"), {
    type: "scatter",
    data: {
      datasets: dims.map((dim) => ({
        label: dimNames[dim],
        data: data.agreement.scatter.filter((p) => p.dim === dim).map((p) => ({ x: p.ai, y: p.human })),
        backgroundColor: colors[dim],
      })),
    },
    options: {
      plugins: { title: { display: true, text: "AI vs 人工" } },
      scales: {
        x: { min: 0.5, max: 5.5, title: { display: true, text: "AI 分" } },
        y: { min: 0.5, max: 5.5, title: { display: true, text: "人工分" } },
      },
    },
  });

  const attrRows = data.attribution.by_category
    .map((row) => `<tr><td>${row.category}</td><td>${row.total}</td><td>${row.failed}</td><td>${pct(row.failure_rate)}</td></tr>`)
    .join("");
  document.getElementById("table-attribution").innerHTML =
    `<tr><th>类别</th><th>需求数</th><th>失败数</th><th>失败率</th></tr>${attrRows}`;
  document.getElementById("status-counts").textContent = Object.entries(data.attribution.status_counts)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");

  document.getElementById("confusion").innerHTML = dims
    .map((dim) => {
      const rows = data.agreement.confusion[dim]
        .map((row, i) => `<tr><td>${i + 1}</td>${row.map((v) => `<td>${v}</td>`).join("")}</tr>`)
        .join("");
      return `<div class="card"><div class="label">${dimNames[dim]}</div><table><tr><th>AI\\人工</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th></tr>${rows}</table></div>`;
    })
    .join("");

  document.getElementById("failure-wall").innerHTML = data.failures
    .map((item) => `
      <div class="card">
        <img src="${item.image}" alt="">
        <div class="hint">${item.query}</div>
        <div>人工 ${fmt(item.human_overall)} / AI ${fmt(item.ai_overall)}</div>
      </div>`)
    .join("") || '<div class="hint">暂无失败案例</div>';

  const sampleRows = data.samples
    .map((s) => `<tr><td>${s.query}</td><td>${fmt(s.ai.overall)}</td><td>${fmt(s.human.overall)}</td></tr>`)
    .join("");
  document.getElementById("sample-table").innerHTML =
    `<tr><th>Query</th><th>AI 总分</th><th>人工总分</th></tr>${sampleRows}`;
})();
```

- [ ] **Step 5: 追加渲染器**

在 `src/imageeval/report.py` 末尾追加：

```python
import base64
import copy
from pathlib import Path

from .storage import resolve_under

WEB_DIR = Path(__file__).parent / "web"


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
    title = f"评测报告 · {data.get('run', {}).get('name', '')}"

    return (
        template.replace("{{TITLE}}", title)
        .replace("{{CSS}}", css)
        .replace("{{CHART_JS}}", chart_js)
        .replace("{{DATA_JSON}}", data_json)
        .replace("{{REPORT_JS}}", report_js)
    )
```

注意：`import` 语句应放到文件顶部（与已有 import 合并），这里为说明追加位置而展示在末尾；实际实现时把 `base64`、`copy`、`Path`、`resolve_under`、`WEB_DIR` 移到顶部 import 区。

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_report_render.py -v`
Expected: `1 passed`

- [ ] **Step 7: 提交**

```bash
git add src/imageeval/web src/imageeval/report.py tests/test_report_render.py
git commit -m "feat: 报告页模板、图表脚本与内嵌渲染器"
```

---

## Task 12: FastAPI 应用与 API

**Files:**
- Create: `src/imageeval/api.py`
- Modify: `src/imageeval/__main__.py`（新增 `serve` 子命令）
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: 全部服务层模块
- Produces:
  - `create_app(cfg: AppConfig, provider: JudgeProvider | None = None) -> FastAPI`
  - 端点：`/api/import`、`/api/batches`、`/api/samples`、`/api/samples/{id}`、`/api/samples/{id}/image`、`/api/runs`、`/api/runs/{id}`、`/api/runs/{id}/start|pause|cancel`、`/api/review/queue`、`/api/evaluations/{id}/review`、`/api/evaluations/{id}/retry`、`/api/reports/summary`、`/report`

- [ ] **Step 1: 写失败测试**

`tests/test_api.py`：

```python
import io
import time

import pytest
from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def _client(cfg, provider=None):
    app = create_app(cfg, provider=provider or FakeProvider())
    return TestClient(app)


def _import_csv(client: TestClient, make_image, tmp_path) -> str:
    image = make_image("api.png", (64, 64))
    csv_bytes = (
        "external_id,query,image,model_name\n"
        f"e1,一只红猫,{image.name},m1\n"
        f"e2,一只蓝狗,{image.name},m1\n"
    ).encode("utf-8")
    response = client.post(
        "/api/import",
        files={"file": ("data.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"image_root": str(image.parent)},
    )
    assert response.status_code == 200, response.text
    return response.json()["batch_id"]


def test_full_api_flow(cfg, make_image) -> None:
    with _client(cfg) as client:
        batch_id = _import_csv(client, make_image, None)

        batches = client.get("/api/batches").json()
        assert batches[0]["id"] == batch_id
        assert batches[0]["sample_count"] == 2

        run_response = client.post(
            "/api/runs", json={"name": "api run", "batch_id": batch_id}
        )
        assert run_response.status_code == 200, run_response.text
        run_id = run_response.json()["run_id"]

        start = client.post(f"/api/runs/{run_id}/start")
        assert start.status_code == 200, start.text

        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] in ("completed", "cancelled"):
                break
            time.sleep(0.1)
        assert run["status"] == "completed"

        queue = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "pending"}
        ).json()
        assert queue["total"] == 2
        item = queue["items"][0]

        review = client.post(
            f"/api/evaluations/{item['evaluation_id']}/review",
            json={"decision": "accepted"},
        )
        assert review.status_code == 200, review.text

        summary = client.get("/api/reports/summary", params={"run_id": run_id}).json()
        assert summary["counts"]["accepted"] == 1
        assert summary["counts"]["ai_done"] == 1

        html = client.get("/report", params={"run_id": run_id})
        assert html.status_code == 200
        assert "window.__REPORT_DATA__" in html.text

        image = client.get(f"/api/samples/{item['sample_id']}/image")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")


def test_unknown_run_returns_404(cfg) -> None:
    with _client(cfg) as client:
        assert client.get("/api/runs/nope").status_code == 404
        assert client.get("/api/reports/summary", params={"run_id": "nope"}).status_code == 404


def test_invalid_review_returns_422(cfg, make_image) -> None:
    with _client(cfg) as client:
        batch_id = _import_csv(client, make_image, None)
        run_id = client.post(
            "/api/runs", json={"name": "r", "batch_id": batch_id}
        ).json()["run_id"]
        client.post(f"/api/runs/{run_id}/start")
        for _ in range(50):
            if client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "completed":
                break
            time.sleep(0.1)
        item = client.get(
            "/api/review/queue", params={"run_id": run_id}
        ).json()["items"][0]

        bad = client.post(
            f"/api/evaluations/{item['evaluation_id']}/review",
            json={"decision": "corrected", "human_adherence": 4},
        )
        assert bad.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.api'`

- [ ] **Step 3: 实现 API**

`src/imageeval/api.py`：

```python
from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AppConfig
from .db import Database, mark_stale_runs, migrate
from .importer import import_file
from .judge import build_provider
from .models import ReviewSubmit
from .pipeline import RunManager, execute_run
from .report import build_summary, render_report_html
from .review import counts, review_queue, submit_review
from .runs import create_run, get_run, list_runs
from .rubric.loader import Rubric, load_rubric
from .storage import ensure_data_dirs, resolve_under

WEB_DIR = Path(__file__).parent / "web"


class RunCreate(BaseModel):
    name: str
    batch_id: str


class _State:
    def __init__(self, cfg: AppConfig, provider=None):
        self.cfg = cfg
        self.provider = provider
        self.db: Database | None = None
        self.rubric: Rubric | None = None
        self.manager: RunManager | None = None


def create_app(cfg: AppConfig, provider=None) -> FastAPI:
    state = _State(cfg, provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_data_dirs(cfg)
        db = Database(cfg.db_path)
        migrate(db.conn)
        rubric = load_rubric(cfg.rubric_path)
        judge = provider or build_provider(cfg, rubric)
        mark_stale_runs(db)
        state.db = db
        state.rubric = rubric
        state.manager = RunManager(db, cfg, judge, rubric)
        app.state.state = state
        yield
        aclose = getattr(judge, "aclose", None)
        if aclose is not None:
            await aclose()
        db.close()

    app = FastAPI(title="imageeval", lifespan=lifespan)

    def db() -> Database:
        assert state.db is not None
        return state.db

    def rubric() -> Rubric:
        assert state.rubric is not None
        return state.rubric

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/import")
    async def api_import(
        file: UploadFile = File(...),
        image_root: str | None = Form(None),
        download: bool = Form(False),
    ) -> dict:
        suffix = Path(file.filename or "upload.csv").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            temp_path = Path(tmp.name)
        try:
            result = await run_in_threadpool(
                import_file,
                db(),
                cfg,
                temp_path,
                Path(image_root) if image_root else None,
                download,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "batch_id": result.batch_id,
            "imported": result.imported,
            "rejected": result.rejected,
            "report": result.report,
        }

    @app.get("/api/batches")
    def api_batches() -> list[dict]:
        return [dict(row) for row in db().query("SELECT * FROM import_batches ORDER BY created_at DESC")]

    @app.get("/api/batches/{batch_id}/report")
    def api_batch_report(batch_id: str) -> dict:
        row = db().query_one("SELECT * FROM import_batches WHERE id = ?", (batch_id,))
        if row is None:
            raise HTTPException(404, "batch not found")
        import json

        return {"batch": dict(row), "report": json.loads(row["report_json"] or "[]")}

    @app.get("/api/samples")
    def api_samples(
        run_id: str,
        state: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        rows = db().query(
            "SELECT s.*, e.status AS eval_status, st.state, e.overall_score, "
            "e.adherence_score, e.quality_score, e.aesthetics_score "
            "FROM samples s "
            "JOIN runs r ON r.batch_id = s.batch_id AND r.id = ? "
            "LEFT JOIN evaluations e ON e.sample_id = s.id AND e.run_id = r.id "
            "LEFT JOIN v_evaluation_state st ON st.id = e.id "
            "WHERE (? IS NULL OR st.state = ?) AND (? IS NULL OR s.query_text LIKE '%' || ? || '%') "
            "ORDER BY s.created_at LIMIT ? OFFSET ?",
            (run_id, state, state, q, q, limit, offset),
        )
        return {
            "items": [
                {
                    "sample_id": row["id"],
                    "external_id": row["external_id"],
                    "query": row["query_text"],
                    "state": row["state"],
                    "model_name": row["model_name"],
                    "thumb_url": f"/api/samples/{row['id']}/image?size=thumb",
                    "ai": {
                        "adherence": row["adherence_score"],
                        "quality": row["quality_score"],
                        "aesthetics": row["aesthetics_score"],
                        "overall": row["overall_score"],
                    },
                }
                for row in rows
            ]
        }

    @app.get("/api/samples/{sample_id}")
    def api_sample_detail(sample_id: str) -> dict:
        row = db().query_one("SELECT * FROM samples WHERE id = ?", (sample_id,))
        if row is None:
            raise HTTPException(404, "sample not found")
        import json

        return {
            **dict(row),
            "tags": json.loads(row["tags_json"] or "[]"),
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    @app.get("/api/samples/{sample_id}/image")
    def api_sample_image(sample_id: str, size: str = "orig") -> FileResponse:
        row = db().query_one(
            "SELECT image_path, thumb_path FROM samples WHERE id = ?", (sample_id,)
        )
        if row is None:
            raise HTTPException(404, "sample not found")
        use_thumb = size == "thumb" and row["thumb_path"]
        relative = row["thumb_path"] if use_thumb else row["image_path"]
        root = cfg.thumbs_dir if use_thumb else cfg.images_dir
        try:
            path = resolve_under(root, relative)
        except ValueError as exc:
            raise HTTPException(400, "invalid image path") from exc
        if not path.exists():
            raise HTTPException(404, "image not found")
        return FileResponse(path)

    @app.post("/api/runs")
    def api_create_run(body: RunCreate) -> dict:
        try:
            run_id = create_run(db(), cfg, rubric(), body.batch_id, body.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/runs")
    def api_list_runs(batch_id: str | None = None) -> list[dict]:
        return list_runs(db(), batch_id)

    @app.get("/api/runs/{run_id}")
    def api_get_run(run_id: str) -> dict:
        try:
            return {"run": get_run(db(), run_id), "counts": counts(db(), run_id)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/runs/{run_id}/start")
    async def api_start_run(run_id: str) -> dict:
        assert state.manager is not None
        existing = db().query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
        if existing is None:
            raise HTTPException(404, "run not found")
        if not state.manager.start(run_id):
            raise HTTPException(409, "run is already running")
        return {"ok": True}

    @app.post("/api/runs/{run_id}/pause")
    def api_pause_run(run_id: str) -> dict:
        assert state.manager is not None
        state.manager.pause(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/cancel")
    def api_cancel_run(run_id: str) -> dict:
        assert state.manager is not None
        state.manager.cancel(run_id)
        return {"ok": True}

    @app.post("/api/evaluations/{evaluation_id}/retry")
    async def api_retry_evaluation(evaluation_id: str) -> dict:
        row = db().query_one(
            "SELECT e.run_id FROM evaluations e WHERE e.id = ?", (evaluation_id,)
        )
        if row is None:
            raise HTTPException(404, "evaluation not found")
        db().execute("DELETE FROM evaluations WHERE id = ? AND status = 'error'", (evaluation_id,))
        run_id = row["run_id"]
        assert state.manager is not None
        state.manager.start(run_id)
        return {"ok": True}

    @app.get("/api/review/queue")
    def api_review_queue(
        run_id: str,
        filter: str = "pending",
        order: str = "default",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        try:
            return review_queue(db(), run_id, filter, order, limit, offset)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/evaluations/{evaluation_id}/review")
    def api_submit_review(evaluation_id: str, payload: ReviewSubmit) -> dict:
        try:
            return submit_review(db(), cfg, rubric(), evaluation_id, payload)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/reports/summary")
    def api_report_summary(run_id: str) -> dict:
        try:
            return build_summary(db(), run_id, rubric())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/report")
    def report_page(run_id: str) -> HTMLResponse:
        try:
            summary = build_summary(db(), run_id, rubric())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return HTMLResponse(render_report_html(summary, cfg.data_dir))

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
```

- [ ] **Step 4: 添加 `serve` 子命令**

在 `src/imageeval/__main__.py` 的 `args = parser.parse_args(argv)` 之前追加：

```python
    subparsers.add_parser("serve", help="启动本地 Web 服务")
```

在 `return 1` 之前追加：

```python
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
        return 0
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_api.py -v`
Expected: `3 passed`

- [ ] **Step 6: 提交**

```bash
git add src/imageeval/api.py src/imageeval/__main__.py tests/test_api.py
git commit -m "feat: FastAPI 服务、导入/评测/复核/报告端点"
```

---

## Task 13: 标注台前端

**Files:**
- Create: `src/imageeval/web/index.html`
- Create: `src/imageeval/web/api.js`
- Create: `src/imageeval/web/app.js`
- Create: `src/imageeval/web/review.js`
- Modify: `src/imageeval/api.py`（新增 `/` 路由）
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: 已有 API 端点、`style.css`
- Produces:
  - 页面 `/`（标注台）
  - 前端事件 `run-changed`（detail: `{runId}`）
  - `GET /api/...` 的全部交互流程

- [ ] **Step 1: 写失败测试**

`tests/test_frontend.py`：

```python
from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def test_index_and_static_assets(cfg) -> None:
    app = create_app(cfg, provider=FakeProvider())
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        for marker in ("btn-accept", "requirements", "image", "run-select"):
            assert marker in index.text

        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "--accent" in css.text

        js = client.get("/static/review.js")
        assert js.status_code == 200
        assert "loadQueue" in js.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_frontend.py -v`
Expected: FAIL，`/` 返回 404

- [ ] **Step 3: 创建标注台 HTML**

`src/imageeval/web/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>生图评测 · 标注台</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <strong>生图评测</strong>
  <select id="batch-select" title="导入批次"></select>
  <input id="run-name" placeholder="评测名称" style="width: 140px">
  <button id="btn-create-run">新建评测</button>
  <select id="run-select" title="选择评测"></select>
  <button id="btn-start" class="primary">开始评分</button>
  <button id="btn-pause">暂停</button>
  <span id="run-progress" class="hint"></span>
  <a id="report-link" href="#" target="_blank">查看报告</a>
  <button id="btn-import">导入数据</button>
</header>

<main class="review">
  <aside class="filters">
    <label>筛选</label>
    <select id="filter">
      <option value="pending">待复核</option>
      <option value="reviewed">已复核</option>
      <option value="skipped">已跳过</option>
      <option value="all">全部</option>
    </select>
    <label>排序</label>
    <select id="order">
      <option value="default">导入顺序</option>
      <option value="low_ai">AI 低分优先</option>
      <option value="max_correction">修正幅度最大</option>
      <option value="random">随机</option>
    </select>
    <button id="btn-refresh">刷新队列</button>
    <div id="progress-text" class="hint"></div>
    <div class="hint">快捷键：A 接受 · J/K 切换 · 1-5 打分 · Enter 保存 · S 跳过 · F 适应图片</div>
  </aside>

  <section class="viewer">
    <div id="image-wrap"><img id="image" alt=""></div>
  </section>

  <section class="panel">
    <div id="state-badge" class="badge"></div>
    <h2>Query</h2>
    <p id="query"></p>

    <h2>AI 需求清单</h2>
    <ul id="requirements" class="requirements"></ul>

    <h2>评分（1-5）</h2>
    <div class="score-row" data-dim="adherence">
      <label>需求遵循</label><input id="score-adherence" type="number" min="1" max="5" step="1">
    </div>
    <div class="score-row" data-dim="quality">
      <label>视觉质量</label><input id="score-quality" type="number" min="1" max="5" step="1">
    </div>
    <div class="score-row" data-dim="aesthetics">
      <label>美学</label><input id="score-aesthetics" type="number" min="1" max="5" step="1">
    </div>

    <details><summary class="hint">子项理由</summary><div id="subscores" class="hint"></div></details>
    <textarea id="note" placeholder="备注（可选）" rows="2"></textarea>

    <div class="actions">
      <button id="btn-accept" class="primary">接受全部 (A)</button>
      <button id="btn-save">保存修正 (Enter)</button>
      <button id="btn-skip">跳过 (S)</button>
    </div>
    <div id="message" class="hint"></div>
  </section>
</main>

<div id="modal-import" class="modal hidden">
  <div class="card">
    <h2 style="margin: 0">导入数据</h2>
    <input id="import-file" type="file" accept=".csv,.jsonl,.ndjson">
    <input id="import-root" placeholder="图片根目录（本地路径图片必填）">
    <label><input id="import-download" type="checkbox"> 下载 URL 图片</label>
    <div class="actions">
      <button id="btn-import-submit" class="primary">导入</button>
      <button id="btn-import-cancel">取消</button>
    </div>
    <pre id="import-result" class="hint"></pre>
  </div>
</div>

<script src="/static/api.js"></script>
<script src="/static/app.js"></script>
<script src="/static/review.js"></script>
</body>
</html>
```

- [ ] **Step 4: 创建前端脚本**

`src/imageeval/web/api.js`：

```js
async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`${response.status}: ${await response.text()}`);
  }
  return response.json();
}

function postJSON(url, body) {
  return getJSON(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function qs(id) {
  return document.getElementById(id);
}
```

`src/imageeval/web/app.js`：

```js
const app = { runId: null, pollTimer: null };

async function refreshBatches() {
  const batches = await getJSON("/api/batches");
  const select = qs("batch-select");
  select.innerHTML = batches
    .map((b) => `<option value="${b.id}">${b.source_name} (${b.sample_count})</option>`)
    .join("");
}

async function refreshRuns() {
  const runs = await getJSON("/api/runs");
  const select = qs("run-select");
  select.innerHTML = runs
    .map((r) => `<option value="${r.id}">${r.name} · ${r.status} · ${r.done}/${r.total}</option>`)
    .join("");
  if (runs.length) {
    const preferred = app.runId && runs.some((r) => r.id === app.runId) ? app.runId : runs[0].id;
    select.value = preferred;
    setRun(preferred);
  }
}

function setRun(runId) {
  app.runId = runId;
  qs("report-link").href = `/report?run_id=${runId}`;
  window.dispatchEvent(new CustomEvent("run-changed", { detail: { runId } }));
  pollRun();
}

async function pollRun() {
  if (!app.runId) return;
  clearTimeout(app.pollTimer);
  try {
    const data = await getJSON(`/api/runs/${app.runId}`);
    const run = data.run;
    qs("run-progress").textContent = `${run.status} · ${run.done}/${run.total} · 失败 ${run.failed}`;
    if (run.status === "running") {
      app.pollTimer = setTimeout(pollRun, 2000);
    }
  } catch (err) {
    qs("run-progress").textContent = String(err.message);
  }
}

async function createRun() {
  const batchId = qs("batch-select").value;
  if (!batchId) {
    alert("请先导入数据");
    return;
  }
  const name = qs("run-name").value.trim() || "未命名评测";
  const result = await postJSON("/api/runs", { name, batch_id: batchId });
  app.runId = result.run_id;
  await refreshRuns();
  qs("run-select").value = result.run_id;
  setRun(result.run_id);
}

async function startRun() {
  if (!app.runId) return;
  await postJSON(`/api/runs/${app.runId}/start`, {});
  pollRun();
}

async function pauseRun() {
  if (!app.runId) return;
  await postJSON(`/api/runs/${app.runId}/pause`, {});
  pollRun();
}

async function submitImport() {
  const file = qs("import-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("image_root", qs("import-root").value.trim());
  form.append("download", qs("import-download").checked ? "true" : "false");
  const response = await fetch("/api/import", { method: "POST", body: form });
  const text = await response.text();
  qs("import-result").textContent = text;
  if (response.ok) {
    await refreshBatches();
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  qs("btn-create-run").onclick = createRun;
  qs("btn-start").onclick = startRun;
  qs("btn-pause").onclick = pauseRun;
  qs("btn-import").onclick = () => qs("modal-import").classList.remove("hidden");
  qs("btn-import-cancel").onclick = () => qs("modal-import").classList.add("hidden");
  qs("btn-import-submit").onclick = submitImport;
  qs("run-select").onchange = (event) => setRun(event.target.value);
  try {
    await refreshBatches();
    await refreshRuns();
  } catch (err) {
    qs("run-progress").textContent = String(err.message);
  }
});
```

`src/imageeval/web/review.js`：

```js
const review = {
  items: [],
  index: 0,
  total: 0,
  runId: null,
  startedAt: 0,
  zoom: 1,
  panX: 0,
  panY: 0,
  focusDim: "adherence",
};

function current() {
  return review.items[review.index];
}

async function loadQueue() {
  if (!review.runId) return;
  const filter = qs("filter").value;
  const order = qs("order").value;
  const data = await getJSON(
    `/api/review/queue?run_id=${encodeURIComponent(review.runId)}&filter=${filter}&order=${order}&limit=200`
  );
  review.items = data.items;
  review.total = data.total;
  review.index = 0;
  render();
}

function render() {
  const item = current();
  if (!item) {
    qs("query").textContent = "当前筛选下没有样本";
    qs("requirements").innerHTML = "";
    qs("subscores").innerHTML = "";
    qs("image").removeAttribute("src");
    qs("progress-text").textContent = "0 / 0";
    return;
  }
  review.startedAt = Date.now();
  qs("state-badge").textContent = item.state;
  qs("query").textContent = item.query;
  qs("image").src = item.image_url;
  review.zoom = 1;
  review.panX = 0;
  review.panY = 0;
  applyTransform();

  qs("requirements").innerHTML = item.ai.requirements
    .map(
      (r) => `
      <li class="${r.status}">
        <div>${r.text}</div>
        <div class="req-meta">${r.category} · ${r.criticality} · ${r.status}</div>
        <div class="hint">${r.evidence || ""}</div>
      </li>`
    )
    .join("");

  const human = item.human;
  qs("score-adherence").value = human?.adherence ?? Math.round(item.ai.adherence);
  qs("score-quality").value = human?.quality ?? Math.round(item.ai.quality);
  qs("score-aesthetics").value = human?.aesthetics ?? Math.round(item.ai.aesthetics);
  qs("note").value = human?.note ?? "";

  const lines = [];
  for (const dim of ["quality", "aesthetics"]) {
    for (const [key, value] of Object.entries(item.ai.subscores[dim] || {})) {
      lines.push(`<div>${dim}.${key}：${value.score ?? "N/A"} ${value.reason || ""}</div>`);
    }
  }
  qs("subscores").innerHTML = lines.join("");
  qs("progress-text").textContent = `${review.index + 1} / ${review.items.length}（筛选共 ${review.total}）`;
  qs("message").textContent = item.ai.verdict || "";
}

function applyTransform() {
  qs("image").style.transform = `translate(${review.panX}px, ${review.panY}px) scale(${review.zoom})`;
}

async function submit(decision) {
  const item = current();
  if (!item) return;
  const payload = {
    decision,
    note: qs("note").value,
    duration_ms: Date.now() - review.startedAt,
  };
  if (decision === "corrected") {
    payload.human_adherence = Number(qs("score-adherence").value);
    payload.human_quality = Number(qs("score-quality").value);
    payload.human_aesthetics = Number(qs("score-aesthetics").value);
  }
  try {
    await postJSON(`/api/evaluations/${item.evaluation_id}/review`, payload);
    review.items.splice(review.index, 1);
    if (review.items.length === 0) {
      await loadQueue();
      return;
    }
    if (review.index >= review.items.length) review.index = 0;
    render();
  } catch (err) {
    qs("message").textContent = `保存失败：${err.message}`;
  }
}

function next() {
  if (review.index < review.items.length - 1) {
    review.index += 1;
    render();
  }
}

function prev() {
  if (review.index > 0) {
    review.index -= 1;
    render();
  }
}

document.addEventListener("keydown", (event) => {
  const tag = event.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") {
    if (event.key === "Enter") {
      event.preventDefault();
      submit("corrected");
    }
    return;
  }
  const key = event.key.toLowerCase();
  if (key === "a") {
    event.preventDefault();
    submit("accepted");
  } else if (key === "s") {
    event.preventDefault();
    submit("skipped");
  } else if (key === "j") {
    event.preventDefault();
    next();
  } else if (key === "k") {
    event.preventDefault();
    prev();
  } else if (key === "f") {
    review.zoom = 1;
    review.panX = 0;
    review.panY = 0;
    applyTransform();
  } else if (/^[1-5]$/.test(key)) {
    qs(`score-${review.focusDim}`).value = key;
    const order = ["adherence", "quality", "aesthetics"];
    review.focusDim = order[(order.indexOf(review.focusDim) + 1) % order.length];
    document
      .querySelectorAll(".score-row")
      .forEach((row) => row.classList.toggle("focused", row.dataset.dim === review.focusDim));
  } else if (key === "enter") {
    event.preventDefault();
    submit("corrected");
  }
});

window.addEventListener("run-changed", (event) => {
  review.runId = event.detail.runId;
  loadQueue();
});

window.addEventListener("DOMContentLoaded", () => {
  qs("btn-accept").onclick = () => submit("accepted");
  qs("btn-save").onclick = () => submit("corrected");
  qs("btn-skip").onclick = () => submit("skipped");
  qs("btn-refresh").onclick = () => loadQueue();
  qs("filter").onchange = () => loadQueue();
  qs("order").onchange = () => loadQueue();
  document.querySelectorAll(".score-row input").forEach((input) => {
    input.addEventListener("focus", () => {
      review.focusDim = input.closest(".score-row").dataset.dim;
      document
        .querySelectorAll(".score-row")
        .forEach((row) => row.classList.toggle("focused", row.dataset.dim === review.focusDim));
    });
  });

  const wrap = qs("image-wrap");
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let baseX = 0;
  let baseY = 0;
  wrap.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 0.87;
      review.zoom = Math.min(8, Math.max(0.2, review.zoom * factor));
      applyTransform();
    },
    { passive: false }
  );
  wrap.addEventListener("pointerdown", (event) => {
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    baseX = review.panX;
    baseY = review.panY;
    wrap.classList.add("dragging");
    wrap.setPointerCapture(event.pointerId);
  });
  wrap.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    review.panX = baseX + (event.clientX - startX);
    review.panY = baseY + (event.clientY - startY);
    applyTransform();
  });
  wrap.addEventListener("pointerup", () => {
    dragging = false;
    wrap.classList.remove("dragging");
  });
});
```

- [ ] **Step 5: 在 API 中挂载首页**

在 `src/imageeval/api.py` 的 `app.mount("/static", ...)` 之前追加：

```python
    @app.get("/")
    def index_page() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_frontend.py -v`
Expected: `1 passed`

- [ ] **Step 7: 手工验收**

```bash
cp config.example.toml config.toml
# 填好 base_url / model，并 export IMAGEEVAL_API_KEY=...
uv run python -m imageeval serve
```

打开 `http://127.0.0.1:8765`，用一份小样本走完：导入 → 新建评测 → 开始评分 → 逐条复核（A/J/K/数字键）。Expected：图片可缩放拖拽，分数预填 AI 值，接受后队列减少，报告链接可打开。

- [ ] **Step 8: 提交**

```bash
git add src/imageeval/web/index.html src/imageeval/web/api.js src/imageeval/web/app.js src/imageeval/web/review.js src/imageeval/api.py tests/test_frontend.py
git commit -m "feat: 标注台前端与键盘复核流程"
```

---

## Task 14: 静态报告导出与 CLI report

**Files:**
- Modify: `src/imageeval/report.py`（追加 `export_static_report`）
- Modify: `src/imageeval/api.py`（新增报告导出与文件下载端点）
- Modify: `src/imageeval/__main__.py`（新增 `report` 子命令）
- Test: `tests/test_report_export.py`

**Interfaces:**
- Consumes: `build_summary`、`render_report_html`、`resolve_under`
- Produces:
  - `export_static_report(summary: dict, data_dir: Path, out_dir: Path) -> Path`
  - `POST /api/reports/export` body `{run_id}` → `{path, url}`
  - `GET /api/files/reports/{name}` → 文件
  - CLI：`python -m imageeval report --run-id ID [--out DIR]`

- [ ] **Step 1: 写失败测试**

`tests/test_report_export.py`：

```python
from imageeval.models import ReviewSubmit
from imageeval.report import build_summary, export_static_report
from imageeval.review import submit_review
from imageeval.runs import create_run
from tests.test_report import _add_eval


def test_export_static_report_inlines_images(db, cfg, rubric, seed_batch) -> None:
    batch_id, sample_ids = seed_batch(1)
    run_id = create_run(db, cfg, rubric, batch_id, "静态报告")
    eval_id = _add_eval(db, run_id, sample_ids[0], (2, 2, 2))
    submit_review(
        db,
        cfg,
        rubric,
        eval_id,
        ReviewSubmit(decision="corrected", human_adherence=1, human_quality=2, human_aesthetics=2),
    )

    summary = build_summary(db, run_id, rubric)
    path = export_static_report(summary, cfg.data_dir, cfg.reports_dir)

    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "data:image/jpeg;base64," in html
    assert "/api/samples/" not in html
    assert "window.__REPORT_DATA__" in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_export.py -v`
Expected: FAIL，`ImportError: cannot import name 'export_static_report'`

- [ ] **Step 3: 实现导出函数**

在 `src/imageeval/report.py` 末尾追加：

```python
def export_static_report(summary: dict, data_dir: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = summary["run"]["id"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"report_{run_id}_{stamp}.html"
    path.write_text(render_report_html(summary, data_dir, inline_images=True), encoding="utf-8")
    return path
```

并在文件顶部 import 区补充：

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: 添加 API 端点**

在 `src/imageeval/api.py` 中追加（放在 `report_page` 之后）：

```python
    class ReportExportRequest(BaseModel):
        run_id: str

    @app.post("/api/reports/export")
    def api_export_report(body: ReportExportRequest) -> dict:
        try:
            summary = build_summary(db(), body.run_id, rubric())
            path = export_static_report(summary, cfg.data_dir, cfg.reports_dir)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"path": str(path), "url": f"/api/files/reports/{path.name}"}

    @app.get("/api/files/reports/{name}")
    def api_report_file(name: str) -> FileResponse:
        try:
            path = resolve_under(cfg.reports_dir, name)
        except ValueError as exc:
            raise HTTPException(400, "invalid file name") from exc
        if not path.exists():
            raise HTTPException(404, "file not found")
        return FileResponse(path)
```

并在 `api.py` 顶部 import 中加入 `export_static_report`。

- [ ] **Step 5: 添加 CLI `report` 子命令**

在 `src/imageeval/__main__.py` 的子命令定义区追加：

```python
    report_parser = subparsers.add_parser("report", help="生成静态 HTML 报告")
    report_parser.add_argument("--run-id", required=True)
    report_parser.add_argument("--out", type=Path, default=None)
```

在 `return 1` 之前追加：

```python
    if args.command == "report":
        from .report import build_summary, export_static_report
        from .rubric.loader import load_rubric

        db = Database(cfg.db_path)
        migrate(db.conn)
        rubric = load_rubric(cfg.rubric_path)
        summary = build_summary(db, args.run_id, rubric)
        path = export_static_report(
            summary, cfg.data_dir, args.out or cfg.reports_dir
        )
        print(str(path))
        db.close()
        return 0
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_report_export.py -v`
Expected: `1 passed`

- [ ] **Step 7: 提交**

```bash
git add src/imageeval/report.py src/imageeval/api.py src/imageeval/__main__.py tests/test_report_export.py
git commit -m "feat: 单文件静态报告导出"
```

---

## Task 15: 训练数据导出

**Files:**
- Create: `src/imageeval/export.py`
- Modify: `src/imageeval/api.py`（新增数据集导出与下载端点）
- Modify: `src/imageeval/__main__.py`（新增 `export` 子命令）
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Database`、`AppConfig`、`resolve_under`、`utcnow`
- Produces:
  - `export_dataset(db, cfg, run_id, mode) -> Path`
  - `POST /api/exports/dataset` body `{run_id, mode}` → `{path, url, count}`
  - `GET /api/exports/{name}/download` → zip
  - CLI：`python -m imageeval export --run-id ID --mode sft|raw|only-reviewed`

- [ ] **Step 1: 写失败测试**

`tests/test_export.py`：

```python
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
        ReviewSubmit(decision="corrected", human_adherence=1, human_quality=2, human_aesthetics=2),
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'imageeval.export'`

- [ ] **Step 3: 实现导出**

`src/imageeval/export.py`：

```python
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .db import Database
from .storage import resolve_under

MODES = ("raw", "sft", "only-reviewed")


def _reviewed(decision: str | None) -> bool:
    return decision in ("accepted", "corrected")


def export_dataset(db: Database, cfg: AppConfig, run_id: str, mode: str) -> Path:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")

    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise LookupError(f"run not found: {run_id}")

    rows = db.query(
        "SELECT s.id AS sample_id, s.query_text, s.image_path, s.model_name, s.tags_json, "
        "e.adherence_score, e.quality_score, e.aesthetics_score, e.overall_score, "
        "e.requirements_json, e.subscores_json, e.verdict, "
        "r.decision, r.human_adherence, r.human_quality, r.human_aesthetics, r.human_overall, "
        "r.note, r.reviewer, r.duration_ms AS review_duration_ms "
        "FROM samples s "
        "JOIN runs rn ON rn.batch_id = s.batch_id AND rn.id = ? "
        "JOIN evaluations e ON e.sample_id = s.id AND e.run_id = rn.id AND e.status = 'ok' "
        "LEFT JOIN reviews r ON r.id = ("
        "  SELECT id FROM reviews WHERE evaluation_id = e.id ORDER BY created_at DESC, id DESC LIMIT 1"
        ") "
        "ORDER BY s.created_at",
        (run_id,),
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = cfg.exports_dir / f"{run_id}_{mode}_{stamp}"
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    manifest_images: list[str] = []
    gold = 0
    silver = 0

    for row in rows:
        reviewed = _reviewed(row["decision"])
        if mode in ("sft", "only-reviewed") and not reviewed:
            continue

        source = resolve_under(cfg.images_dir, row["image_path"])
        suffix = source.suffix.lower() or ".png"
        image_rel = f"images/{row['sample_id']}{suffix}"
        shutil.copy2(source, out_dir / image_rel)
        manifest_images.append(image_rel)

        ai_scores = {
            "adherence": row["adherence_score"],
            "quality": row["quality_score"],
            "aesthetics": row["aesthetics_score"],
            "overall": row["overall_score"],
        }
        if reviewed:
            gold += 1
            final_scores = {
                "adherence": row["human_adherence"],
                "quality": row["human_quality"],
                "aesthetics": row["human_aesthetics"],
                "overall": row["human_overall"],
            }
            human = {
                "adherence": row["human_adherence"],
                "quality": row["human_quality"],
                "aesthetics": row["human_aesthetics"],
                "overall": row["human_overall"],
                "note": row["note"] or "",
                "reviewer": row["reviewer"],
                "decision": row["decision"],
            }
            label_quality = "gold"
            final_source = "human"
        else:
            silver += 1
            final_scores = dict(ai_scores)
            human = None
            label_quality = "silver"
            final_source = "ai"

        if mode == "sft":
            records.append(
                {
                    "image": image_rel,
                    "query": row["query_text"],
                    "label": final_scores,
                    "label_quality": label_quality,
                    "meta": {
                        "sample_id": row["sample_id"],
                        "rubric_version": run["rubric_version"],
                        "reviewer": row["reviewer"],
                        "model_name": row["model_name"],
                    },
                }
            )
            continue

        records.append(
            {
                "sample_id": row["sample_id"],
                "query": row["query_text"],
                "image": image_rel,
                "model_name": row["model_name"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "rubric_version": run["rubric_version"],
                "prompt_hash": run["prompt_hash"],
                "judge": {"provider": run["provider"], "model": run["judge_model"]},
                "ai": {
                    **ai_scores,
                    "requirements": json.loads(row["requirements_json"] or "[]"),
                    "subscores": json.loads(row["subscores_json"] or "{}"),
                    "verdict": row["verdict"],
                },
                "human": human,
                "final": {
                    "scores": final_scores,
                    "source": final_source,
                    "label_quality": label_quality,
                },
                "meta": {
                    "created_at": run["created_at"],
                    "review_duration_ms": row["review_duration_ms"],
                },
            }
        )

    with (out_dir / "dataset.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "run_id": run_id,
        "mode": mode,
        "rubric_version": run["rubric_version"],
        "prompt_hash": run["prompt_hash"],
        "judge": {"provider": run["provider"], "model": run["judge_model"]},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"total": len(records), "gold": gold, "silver": silver},
        "images": manifest_images,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir
```

- [ ] **Step 4: 添加 API 端点**

在 `src/imageeval/api.py` 中追加（放在导出报告端点之后）：

```python
    class DatasetExportRequest(BaseModel):
        run_id: str
        mode: str = "sft"

    @app.post("/api/exports/dataset")
    async def api_export_dataset(body: DatasetExportRequest) -> dict:
        try:
            out_dir = await run_in_threadpool(
                export_dataset, db(), cfg, body.run_id, body.mode
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        import shutil

        zip_base = out_dir
        shutil.make_archive(str(zip_base), "zip", root_dir=out_dir)
        zip_path = zip_base.with_suffix(".zip")
        with (out_dir / "dataset.jsonl").open(encoding="utf-8") as fh:
            count = sum(1 for _ in fh)
        return {
            "path": str(out_dir),
            "url": f"/api/exports/{zip_path.name}/download",
            "count": count,
        }

    @app.get("/api/exports/{name}/download")
    def api_download_export(name: str) -> FileResponse:
        if not name.endswith(".zip"):
            raise HTTPException(400, "only zip downloads are supported")
        try:
            path = resolve_under(cfg.exports_dir, name)
        except ValueError as exc:
            raise HTTPException(400, "invalid file name") from exc
        if not path.exists():
            raise HTTPException(404, "file not found")
        return FileResponse(path, filename=name)
```

并在 `api.py` 顶部 import 中加入 `export_dataset`。

- [ ] **Step 5: 添加 CLI `export` 子命令**

在 `__main__.py` 子命令定义区追加：

```python
    export_parser = subparsers.add_parser("export", help="导出训练数据")
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument("--mode", choices=["raw", "sft", "only-reviewed"], default="sft")
```

在 `return 1` 之前追加：

```python
    if args.command == "export":
        from .export import export_dataset

        db = Database(cfg.db_path)
        migrate(db.conn)
        path = export_dataset(db, cfg, args.run_id, args.mode)
        print(str(path))
        db.close()
        return 0
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_export.py -v`
Expected: `4 passed`

- [ ] **Step 7: 提交**

```bash
git add src/imageeval/export.py src/imageeval/api.py src/imageeval/__main__.py tests/test_export.py
git commit -m "feat: gold/silver 分级训练数据导出与下载"
```

---

## Task 16: 端到端验收与文档

**Files:**
- Create: `tests/test_e2e.py`
- Create: `README.md`
- Modify: `.gitignore`
- Test: 全量 `tests/`

**Interfaces:**
- Consumes: 全部模块
- Produces: 可复现的端到端验收与使用文档

- [ ] **Step 1: 写端到端测试**

`tests/test_e2e.py`：

```python
import io
import time

from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def test_end_to_end_import_score_review_report_export(cfg, make_image) -> None:
    image = make_image("e2e.png", (96, 96))
    csv_bytes = (
        "external_id,query,image,model_name,tags\n"
        f"e1,一只红色的猫,{image.name},m1,a;b\n"
        f"e2,一只蓝色的狗,{image.name},m1,c\n"
    ).encode("utf-8")

    app = create_app(cfg, provider=FakeProvider(adherence=3, quality=3, aesthetics=4))
    with TestClient(app) as client:
        imported = client.post(
            "/api/import",
            files={"file": ("e2e.csv", io.BytesIO(csv_bytes), "text/csv")},
            data={"image_root": str(image.parent)},
        )
        assert imported.status_code == 200, imported.text
        batch_id = imported.json()["batch_id"]

        run_id = client.post(
            "/api/runs", json={"name": "e2e", "batch_id": batch_id}
        ).json()["run_id"]
        assert client.post(f"/api/runs/{run_id}/start").status_code == 200

        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] == "completed":
                break
            time.sleep(0.1)
        assert run["status"] == "completed"
        assert run["done"] == 2

        queue = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "pending"}
        ).json()
        for item in queue["items"]:
            response = client.post(
                f"/api/evaluations/{item['evaluation_id']}/review",
                json={
                    "decision": "corrected",
                    "human_adherence": 2,
                    "human_quality": 3,
                    "human_aesthetics": 4,
                    "note": "端到端",
                    "duration_ms": 1200,
                },
            )
            assert response.status_code == 200, response.text

        summary = client.get("/api/reports/summary", params={"run_id": run_id}).json()
        assert summary["counts"]["reviewed"] == 2
        assert summary["acceptance_rate"] == 0.0
        assert summary["agreement"]["mae"]["adherence"] == pytest.approx(2.5)

        report = client.post("/api/reports/export", json={"run_id": run_id})
        assert report.status_code == 200
        report_url = report.json()["url"]
        assert client.get(report_url).status_code == 200

        dataset = client.post(
            "/api/exports/dataset", json={"run_id": run_id, "mode": "sft"}
        )
        assert dataset.status_code == 200, dataset.text
        assert dataset.json()["count"] == 2
        assert client.get(dataset.json()["url"]).status_code == 200
```

- [ ] **Step 2: 运行端到端测试**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: `1 passed`

- [ ] **Step 3: 写 README**

`README.md`：

```markdown
# imageeval · 生图模型评测系统

对「原始 Query + 生成图片」做需求遵循、视觉质量、美学三维评测，支持 AI 预标注、人工复核、可视化报告与训练数据导出。

## 快速开始

```bash
uv sync --extra dev
cp config.example.toml config.toml   # 填写 base_url / model
export IMAGEEVAL_API_KEY="你的密钥"
uv run python -m imageeval serve
```

打开 http://127.0.0.1:8765 。

## 数据格式

CSV 列或 JSONL 字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| external_id | 是 | 批内唯一 |
| query | 是 | 原始提示词 |
| image | 是 | 本地路径（相对 `--image-root` 或文件所在目录）或 URL |
| model_name | 否 | 生成模型标识 |
| tags | 否 | 分号分隔，或 JSON 数组 |
| metadata | 否 | JSON 对象字符串 |

## CLI

```bash
uv run python -m imageeval import data.csv --image-root ./images
uv run python -m imageeval run --new --batch-id BATCH --name "第一轮"
uv run python -m imageeval report --run-id RUN
uv run python -m imageeval export --run-id RUN --mode sft
```

## 评分口径

- 需求遵循 0.40、视觉质量 0.35、美学 0.25；全部权重在 `src/imageeval/rubric/v1.yaml`。
- 需求遵循由原子需求状态本地计算，critical 冲突封顶。
- 人工分 1-5 整数；AI 维度分保留两位小数。
- 导出区分 `gold`（人工复核）与 `silver`（仅 AI）。

## 测试

```bash
uv run pytest -v
```

测试不发起任何真实网络请求。
```

- [ ] **Step 4: 添加 .gitignore**

`.gitignore`：

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
config.toml
data/
```

- [ ] **Step 5: 运行全量测试**

Run: `uv run pytest -v`
Expected: 全部通过（约 30+ 个用例）

- [ ] **Step 6: 提交**

```bash
git add README.md .gitignore tests/test_e2e.py
git commit -m "test: 端到端验收与使用文档"
```

---

## 附录 A：学习点参考实现

> 仅在用户明确委托时使用。先让用户尝试实现。

### A.1 `scoring.aggregate_adherence`

```python
def aggregate_adherence(requirements: list[Requirement], intent_alignment: int) -> float:
    if not requirements:
        raise ValueError("requirements must not be empty")

    status_value = {
        "satisfied": 1.0,
        "partial": 0.5,
        "missing": 0.0,
        "contradicted": 0.0,
    }
    total_weight = 0.0
    total_value = 0.0
    critical_contradicted = False

    for requirement in requirements:
        weight = 3.0 if requirement.criticality == "critical" else 1.0
        total_weight += weight
        total_value += weight * status_value[requirement.status]
        if requirement.criticality == "critical" and requirement.status == "contradicted":
            critical_contradicted = True

    atomic = 1.0 + 4.0 * (total_value / total_weight)
    if critical_contradicted:
        atomic = min(atomic, 3.0)
    return round(0.75 * atomic + 0.25 * intent_alignment, 2)
```

### A.2 `report.select_failure_cases`

```python
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
```

---

## 自审：规格覆盖矩阵

| 规格章节 | 覆盖任务 |
|---|---|
| §3 目录结构 | Task 1-15 |
| §4 六张表与视图 | Task 2 |
| §5.1 评分尺度 | Task 4（rubric anchors） |
| §5.2 需求遵循公式 | Task 4（学习点 + 附录 A.1） |
| §5.3/5.4 子项权重与 N/A 重归一 | Task 4 |
| §5.5 总分权重 | Task 4 |
| §5.6 JSON 契约与修复重试 | Task 3、Task 7 |
| §6 导入/并发/限流/重试/续跑/成本 | Task 5、Task 8 |
| §7 复核状态机/标注台/快捷键 | Task 9、Task 13 |
| §8 报告六模块 | Task 10、Task 11、Task 14 |
| §9 训练数据三种模式与 gold/silver | Task 15 |
| §10 路径安全/密钥/不丢数据/幂等 | Task 5、Task 7、Task 8 |
| §11 测试策略 | Task 1-16 |
| §12 API 一览 | Task 12、Task 14、Task 15 |
| §13 CLI | Task 5、Task 8、Task 12、Task 14、Task 15 |
| §14 配置 | Task 1 |
| §15 里程碑 | Task 1-5（M1）、6-8（M2）、9-13（M3）、14-16（M4） |
| §16 学习点 | Task 4、Task 10 + 附录 A |
