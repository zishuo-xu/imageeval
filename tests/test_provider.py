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
