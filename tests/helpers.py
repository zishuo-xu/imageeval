from __future__ import annotations

from imageeval.checks import CHECKS


def valid_judge_payload(score: int = 4) -> dict:
    def sub(value: int) -> dict:
        return {"score": value, "reason": "理由"}

    return {
        "quality_gate": {"delivery": "ready", "required_edits": [], "excellence": []},
        "feedback": {"rating": "满意", "positive_points": ["符合提示词"], "negative_points": [], "explanation": "画面中央猫的主体符合原始需求"},
        "observation": "画面中有一只红色的猫。",
        "requirements": [
            {
                "text": "红色的猫",
                "category": "subject",
                "criticality": "critical",
                "status": "satisfied",
                "evidence": "画面中央的猫为红色",
            }
        ],
        "intent_alignment": score,
        "subscores": {
            "checks": [{"key":key,"status":"not_applicable","location":"测试图","evidence":"离线格式测试"} for key in CHECKS],
            "quality": {
                "clarity": sub(score),
                "artifacts": sub(score),
                "text_render": {"score": None, "reason": "无文字", "na": True},
                "physics": sub(score),
                "consistency": sub(score),
            },
            "aesthetics": {
                "composition": sub(score),
                "color": sub(score),
                "lighting": sub(score),
                "texture": sub(score),
                "appeal": sub(score),
            },
        },
        "notable_issues": [],
        "verdict": "整体符合要求",
    }
