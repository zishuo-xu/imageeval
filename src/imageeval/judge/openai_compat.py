from __future__ import annotations

import json
import os
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


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
        api_key = os.environ.get(self._cfg.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
            "max_tokens": self._cfg.max_tokens,
        }
        if self._cfg.json_mode:
            payload["response_format"] = {"type": "json_object"}
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

        if data["choices"][0].get("finish_reason") == "length":
            raise FatalJudgeError("评分输出达到 max_tokens 上限被截断，请提高输出上限后新建评测")

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
        last_raw = ""
        total_in = 0
        total_out = 0

        for attempt in (1, 2):
            content, usage = await self._post(messages)
            if not isinstance(usage, dict):
                usage = {}
            last_raw = content
            total_in += _as_int(usage.get("prompt_tokens"))
            total_out += _as_int(usage.get("completion_tokens"))
            try:
                parsed = parse_judge_output(content)
                if parsed.feedback is None or not parsed.feedback.explanation.strip():
                    raise ValueError("feedback with rating, positive_points, negative_points and explanation is required")
                if parsed.feedback.rating in ("非常满意", "满意") and not parsed.feedback.positive_points:
                    raise ValueError("satisfied feedback needs at least one positive point")
                if parsed.feedback.rating in ("不满意", "非常不满意") and not parsed.feedback.negative_points:
                    raise ValueError("dissatisfied feedback needs at least one negative point")
                if parsed.feedback.rating in ("非常满意", "满意") and (any(c.status in ("major", "severe") for c in parsed.subscores.checks) or any(r.criticality == "critical" and r.status in ("missing", "contradicted") for r in parsed.requirements)):
                    raise ValueError("major defects or unmet critical requirements cannot be rated satisfied")
                gate = parsed.quality_gate
                if gate is None:
                    raise ValueError("quality_gate with delivery, required_edits, excellence is required")
                rating = parsed.feedback.rating
                if gate.delivery == "minor_edits" and rating in ("非常满意", "满意"):
                    raise ValueError("required local edits cap satisfaction at 一般")
                if gate.delivery == "major_edits" and rating not in ("不满意", "非常不满意"):
                    raise ValueError("major edits cap satisfaction at 不满意")
                if gate.delivery == "unusable" and rating != "非常不满意":
                    raise ValueError("unusable must be rated 非常不满意")
                if rating in ("非常满意", "满意") and any(r.status != "satisfied" for r in parsed.requirements):
                    raise ValueError("unmet or partial explicit requirements cannot be rated satisfied")
                if rating == "非常满意" and (len(gate.excellence) < 2 or parsed.feedback.negative_points or parsed.notable_issues or any(c.status in ("minor", "major", "severe") for c in parsed.subscores.checks)):
                    raise ValueError("非常满意 needs two distinct outstanding evidence items and no identified issues")
                if any(c.status == "severe" for c in parsed.subscores.checks) and rating != "非常不满意":
                    raise ValueError("severe unusable structural defects must be rated 非常不满意")
                if not parsed.subscores.checks:
                    raise ValueError("subscores.checks is required: include all 12 visual checks")
            except Exception as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"输出不合法：{exc}。只输出完整 JSON；subscores.checks 必须含全部 12 项，不可放在顶层或 quality 内。不要输出其他文字。",
                    },
                ]
                continue

            return JudgeResponse(
                raw=content,
                parsed=parsed,
                tokens_in=total_in,
                tokens_out=total_out,
                latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
                parse_attempts=attempt,
            )

        raise SchemaJudgeError(
            f"invalid judge output after repair: {last_error}",
            raw=last_raw,
            attempts=2,
        )
