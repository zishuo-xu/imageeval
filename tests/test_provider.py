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
    with pytest.raises(SchemaJudgeError) as info:
        await provider.evaluate("q", make_image())

    assert len(bodies) == 2
    assert "输出不合法" in bodies[1]["messages"][-1]["content"]
    assert info.value.raw == "not json"
    assert info.value.attempts == 2


async def test_schema_error_then_success(rubric, make_image) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "oops"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                },
            )
        return _ok_response()

    provider = _provider(handler, rubric)
    response = await provider.evaluate("q", make_image())
    assert response.parse_attempts == 2
    assert response.tokens_in == 16
    assert response.tokens_out == 29


async def test_500_is_retryable(rubric, make_image) -> None:
    provider = _provider(lambda request: httpx.Response(500, json={"error": "boom"}), rubric)
    with pytest.raises(RetryableJudgeError):
        await provider.evaluate("q", make_image())


async def test_read_timeout_is_retryable(rubric, make_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(handler, rubric)
    with pytest.raises(RetryableJudgeError):
        await provider.evaluate("q", make_image())


async def test_null_usage_defaults_to_zero(rubric, make_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_judge_payload(), ensure_ascii=False
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": None, "completion_tokens": None},
            },
        )

    provider = _provider(handler, rubric)
    response = await provider.evaluate("q", make_image())
    assert response.tokens_in == 0
    assert response.tokens_out == 0
    assert response.parsed.intent_alignment == 4


async def test_non_dict_usage_defaults_to_zero(rubric, make_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_judge_payload(), ensure_ascii=False
                            )
                        }
                    }
                ],
                "usage": "oops",
            },
        )

    provider = _provider(handler, rubric)
    response = await provider.evaluate("q", make_image())
    assert response.tokens_in == 0
    assert response.tokens_out == 0
    assert response.parsed.intent_alignment == 4


async def test_api_key_header_sent_when_env_set(rubric, make_image, monkeypatch) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return _ok_response()

    monkeypatch.setenv("IMAGEEVAL_API_KEY", "secret-token")
    provider = _provider(handler, rubric)
    await provider.evaluate("q", make_image())
    assert seen == ["Bearer secret-token"]


async def test_api_key_header_absent_when_env_unset(rubric, make_image, monkeypatch) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return _ok_response()

    monkeypatch.delenv("IMAGEEVAL_API_KEY", raising=False)
    provider = _provider(handler, rubric)
    await provider.evaluate("q", make_image())
    assert seen == [None]
