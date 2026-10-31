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
