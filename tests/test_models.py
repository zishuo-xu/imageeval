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
