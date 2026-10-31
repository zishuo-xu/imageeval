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
            except Exception as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"输出不合法：{exc}。只输出符合 schema 的 JSON 对象，不要输出其他文字。",
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
