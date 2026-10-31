from __future__ import annotations

from dataclasses import dataclass

from .models import JudgeOutput, Requirement, SubScore
from .rubric.loader import Rubric


@dataclass(frozen=True)
class EvaluationScores:
    adherence: float
    quality: float
    aesthetics: float
    overall: float


def aggregate_adherence(requirements: list[Requirement], intent_alignment: int) -> float:
    if not requirements:
        raise ValueError("requirements must not be empty")

    status_value = {
        "satisfied": 1.0,
        "partial": 0.5,
        "missing": 0.0,
        "contradicted": 0.0,
    }
    total_weight = 0.0
    total_value = 0.0
    critical_contradicted = False

    for requirement in requirements:
        weight = 3.0 if requirement.criticality == "critical" else 1.0
        total_weight += weight
        total_value += weight * status_value[requirement.status]
        if requirement.criticality == "critical" and requirement.status == "contradicted":
            critical_contradicted = True

    atomic = 1.0 + 4.0 * (total_value / total_weight)
    if critical_contradicted:
        atomic = min(atomic, 3.0)
    return round(0.75 * atomic + 0.25 * intent_alignment, 2)


def _dimension_score(subscores: dict[str, SubScore], weights: dict[str, float]) -> float:
    applicable = {
        key: item
        for key, item in subscores.items()
        if not item.na and item.score is not None
    }
    if len(applicable) * 2 < len(subscores):
        raise ValueError("insufficient applicable subscores")
    weight_sum = sum(weights[key] for key in applicable)
    score = sum(weights[key] * applicable[key].score for key in applicable) / weight_sum
    return round(score, 2)


def compute_overall(
    adherence: float, quality: float, aesthetics: float, rubric: Rubric
) -> float:
    w = rubric.dimension_weights
    return round(
        w["adherence"] * adherence + w["quality"] * quality + w["aesthetics"] * aesthetics,
        2,
    )


def compute_scores(output: JudgeOutput, rubric: Rubric) -> EvaluationScores:
    adherence = aggregate_adherence(output.requirements, output.intent_alignment)
    quality = _dimension_score(dict(output.subscores.quality), rubric.subscore_weights["quality"])
    aesthetics = _dimension_score(
        dict(output.subscores.aesthetics), rubric.subscore_weights["aesthetics"]
    )
    overall = compute_overall(adherence, quality, aesthetics, rubric)
    return EvaluationScores(
        adherence=adherence,
        quality=quality,
        aesthetics=aesthetics,
        overall=overall,
    )
