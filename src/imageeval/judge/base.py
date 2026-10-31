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

    def __init__(self, message: str, raw: str = "", attempts: int = 1):
        super().__init__(message)
        self.raw = raw
        self.attempts = attempts


class JudgeProvider(Protocol):
    name: str
    model: str

    async def evaluate(self, query: str, image_path: Path) -> JudgeResponse: ...
