from __future__ import annotations

import hashlib

from ..rubric.loader import Rubric

PROMPT_VERSION = "p1"

SYSTEM_TEMPLATE = """你是严格的文生图质量评测专家。你的任务是依据给定评分标准，评估「原始 Query」与「生成图片」的匹配程度。

评分尺度（1-5 整数）：
{anchors}

必须遵守的流程：
1. 先写 observation：客观描述画面里实际有什么（人物、物体、数量、颜色、文字、空间关系、风格）。不要评价，只描述。
2. 把 Query 拆成原子需求 requirements，每条包含：
   - text：需求内容
   - category：subject / attribute / count / relation / style / text_render / negative
   - criticality：critical（主体、数量、明确否定约束等，不满足则任务失败）或 normal
   - status：satisfied / partial / missing / contradicted
   - evidence：图中支持该判定的具体位置或内容
   requirements 不得为空，且至少一条必须是 critical。
   negative 需求表示「不要出现 X」，status=satisfied 表示图中没有出现 X。
3. 给出 intent_alignment（1-5 整数）：整体意图是否贴合 Query，即使细节有出入。
4. 给视觉质量子项打分：clarity / artifacts / text_render / physics / consistency。
   若 Query 没有文字要求且画面不需要文字，text_render 的 score 设为 null、na 设为 true。
5. 给美学子项打分：composition / color / lighting / texture / appeal。
6. 所有子项都必须给出 reason（简短中文）。
7. 输出必须是一个 JSON 对象，不要输出 Markdown 代码块，不要输出任何 JSON 之外的文字。

JSON 结构（字段名与层级必须完全一致）：
{{
  "observation": "画面客观描述",
  "requirements": [
    {{"text": "红色雨伞", "category": "attribute", "criticality": "critical",
      "status": "satisfied", "evidence": "画面中央偏左有一把红色雨伞"}}
  ],
  "intent_alignment": 4,
  "subscores": {{
    "quality": {{
      "clarity": {{"score": 4, "reason": "清晰度良好"}},
      "artifacts": {{"score": 3, "reason": "左手手指数量异常"}},
      "text_render": {{"score": null, "reason": "画面无文字要求", "na": true}},
      "physics": {{"score": 4, "reason": "透视与光影合理"}},
      "consistency": {{"score": 4, "reason": "风格统一"}}
    }},
    "aesthetics": {{
      "composition": {{"score": 4, "reason": "构图稳定"}},
      "color": {{"score": 5, "reason": "配色和谐"}},
      "lighting": {{"score": 4, "reason": "光线自然"}},
      "texture": {{"score": 3, "reason": "质感一般"}},
      "appeal": {{"score": 4, "reason": "整体有吸引力"}}
    }}
  }},
  "notable_issues": ["左手手指异常"],
  "verdict": "一句话结论"
}}"""


def _anchors_text(rubric: Rubric) -> str:
    return "\n".join(f"{score} = {text}" for score, text in sorted(rubric.anchors.items()))


def prompt_hash(rubric: Rubric) -> str:
    material = f"{PROMPT_VERSION}|{rubric.version}|{SYSTEM_TEMPLATE}|{_anchors_text(rubric)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_messages(query: str, image_data_url: str, rubric: Rubric) -> list[dict]:
    system = SYSTEM_TEMPLATE.format(anchors=_anchors_text(rubric))
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"原始 Query：\n{query}"},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]
