import pytest

from imageeval.models import JudgeOutput, Requirement, SubScore
from imageeval.scoring import aggregate_adherence, compute_overall, compute_scores


def _req(criticality="critical", status="satisfied") -> Requirement:
    return Requirement(
        text="x", category="subject", criticality=criticality, status=status
    )


def _output(adherence_status="satisfied", intent=5, quality=4, aesthetics=4) -> JudgeOutput:
    def sub(score):
        return SubScore(score=score, reason="r")

    return JudgeOutput.model_validate(
        {
            "observation": "o",
            "requirements": [
                {
                    "text": "主体",
                    "category": "subject",
                    "criticality": "critical",
                    "status": adherence_status,
                    "evidence": "e",
                }
            ],
            "intent_alignment": intent,
            "subscores": {
                "quality": {
                    "clarity": {"score": quality, "reason": "r"},
                    "artifacts": {"score": quality, "reason": "r"},
                    "text_render": {"score": None, "reason": "na", "na": True},
                    "physics": {"score": quality, "reason": "r"},
                    "consistency": {"score": quality, "reason": "r"},
                },
                "aesthetics": {
                    "composition": {"score": aesthetics, "reason": "r"},
                    "color": {"score": aesthetics, "reason": "r"},
                    "lighting": {"score": aesthetics, "reason": "r"},
                    "texture": {"score": aesthetics, "reason": "r"},
                    "appeal": {"score": aesthetics, "reason": "r"},
                },
            },
            "notable_issues": [],
            "verdict": "v",
        }
    )


def test_all_satisfied_reaches_max() -> None:
    assert aggregate_adherence([_req()], 5) == pytest.approx(5.0)


def test_partial_credit_and_normal_weight() -> None:
    reqs = [_req("critical", "satisfied"), _req("normal", "partial")]
    assert aggregate_adherence(reqs, 5) == pytest.approx(4.62, abs=0.01)


def test_critical_contradiction_caps_atomic_component() -> None:
    assert aggregate_adherence([_req("critical", "contradicted")], 5) == pytest.approx(2.0)


def test_compute_scores_uses_rubric_weights(rubric) -> None:
    scores = compute_scores(_output(quality=4, aesthetics=4), rubric)
    assert scores.adherence == pytest.approx(5.0)
    assert scores.quality == pytest.approx(4.0)
    assert scores.aesthetics == pytest.approx(4.0)
    assert scores.overall == pytest.approx(4.4)


def test_na_renormalizes_quality(rubric) -> None:
    output = _output(quality=4)
    output.subscores.quality.artifacts = SubScore(score=2, reason="bad")
    scores = compute_scores(output, rubric)
    expected = (0.20 * 4 + 0.30 * 2 + 0.20 * 4 + 0.20 * 4) / 0.90
    assert scores.quality == pytest.approx(round(expected, 2))


def test_insufficient_subscores_raises(rubric) -> None:
    output = _output()
    output.subscores.quality.clarity = SubScore(score=None, reason="na", na=True)
    output.subscores.quality.physics = SubScore(score=None, reason="na", na=True)
    output.subscores.quality.consistency = SubScore(score=None, reason="na", na=True)
    with pytest.raises(ValueError, match="insufficient applicable"):
        compute_scores(output, rubric)


def test_compute_overall(rubric) -> None:
    assert compute_overall(4, 3, 5, rubric) == pytest.approx(3.9)
