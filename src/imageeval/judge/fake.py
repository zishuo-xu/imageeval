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
from ..feedback import Feedback
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
            feedback=Feedback(rating="满意", positive_points=["符合提示词"], explanation="模拟评价，仅用于功能测试"),
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
