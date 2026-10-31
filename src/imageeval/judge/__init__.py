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
