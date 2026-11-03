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
    json_mode: bool = False
    temperature: float = 0.2
    max_tokens: int = 8192
    timeout_s: float = 90.0
    image_max_edge: int = 1280


@dataclass(frozen=True)
class GenerationConfig:
    base_url: str = "https://api.minimax.cn/v1"
    model: str = "image-01"
    api_key_env: str = "MINIMAX_API_KEY"
    timeout_s: float = 180.0


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
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    pe: JudgeConfig | None = None

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
        generation=GenerationConfig(**raw.get("generation", {})),
        pe=JudgeConfig(**raw["pe"]) if "pe" in raw else None,
    )
