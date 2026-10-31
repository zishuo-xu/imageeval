from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from .util import round_half_up

Score = Annotated[int, Field(ge=1, le=5)]
Category = Literal["subject", "attribute", "count", "relation", "style", "text_render", "negative"]
Criticality = Literal["critical", "normal"]
Status = Literal["satisfied", "partial", "missing", "contradicted"]


class Requirement(BaseModel):
    text: str = Field(min_length=1)
    category: Category
    criticality: Criticality
    status: Status
    evidence: str = ""


class SubScore(BaseModel):
    score: Score | None = None
    reason: str = ""
    na: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        score = data.get("score")
        na = bool(data.get("na", False))
        if isinstance(score, float):
            score = round_half_up(score)
        if na:
            score = None
        return {**data, "score": score, "na": na}

    @model_validator(mode="after")
    def _require_score_unless_na(self) -> "SubScore":
        if not self.na and self.score is None:
            raise ValueError("score is required unless na=true")
        return self


class QualitySubscores(BaseModel):
    clarity: SubScore
    artifacts: SubScore
    text_render: SubScore
    physics: SubScore
    consistency: SubScore


class AestheticSubscores(BaseModel):
    composition: SubScore
    color: SubScore
    lighting: SubScore
    texture: SubScore
    appeal: SubScore


class Subscores(BaseModel):
    quality: QualitySubscores
    aesthetics: AestheticSubscores


class JudgeOutput(BaseModel):
    observation: str = ""
    requirements: list[Requirement] = Field(min_length=1)
    intent_alignment: Score
    subscores: Subscores
    notable_issues: list[str] = Field(default_factory=list)
    verdict: str = ""

    @model_validator(mode="before")
    @classmethod
    def _round_intent_alignment(cls, data: Any) -> Any:
        if isinstance(data, dict):
            value = data.get("intent_alignment")
            if isinstance(value, float):
                data = {**data, "intent_alignment": round_half_up(value)}
        return data

    @model_validator(mode="after")
    def _require_critical(self) -> "JudgeOutput":
        if not any(item.criticality == "critical" for item in self.requirements):
            raise ValueError("at least one requirement must be critical")
        return self


class ReviewSubmit(BaseModel):
    decision: Literal["accepted", "corrected", "skipped"]
    human_adherence: Score | None = None
    human_quality: Score | None = None
    human_aesthetics: Score | None = None
    reasons: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    duration_ms: int = 0

    @model_validator(mode="after")
    def _corrected_requires_scores(self) -> "ReviewSubmit":
        if self.decision == "corrected":
            for field in ("human_adherence", "human_quality", "human_aesthetics"):
                if getattr(self, field) is None:
                    raise ValueError(f"{field} is required when decision=corrected")
        return self


def parse_judge_output(content: str) -> JudgeOutput:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in response")
    data = json.loads(text[start : end + 1])
    return JudgeOutput.model_validate(data)
