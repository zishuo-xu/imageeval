from __future__ import annotations

import hashlib
import json

from ..rubric.loader import Rubric
from ..checks import CHECKS, CHECKLIST_VERSION

from ..feedback import RATINGS, POSITIVE_POINTS, NEGATIVE_POINTS, RATING_CRITERIA, RATING_POLICY_VERSION

PROMPT_VERSION = "p4-strict-satisfaction"

SYSTEM_TEMPLATE = """你是严格的文生图质量评测专家。你的任务是依据给定评分标准，评估「原始 Query」与「生成图片」的匹配程度。

评分尺度（1-5 整数）：
{anchors}

必须遵守的流程：
1. 先写 observation：客观描述画面里实际有什么（人物、物体、数量、颜色、文字、空间关系、风格）。不要评价，只描述。
2. 把 Query 拆成原子需求 requirements，每条包含：
   - text：需求内容
   - category：subject / attribute / count / relation / style / text_render / negative
   - criticality：critical（主体、数量、用户明确要求的动作/场景/文字/属性、否定约束，不满足则任务失败）或 normal
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

JSON 结构（字段名与层级必须完全一致；示例分数仅展示格式，不是默认值）：
{{
  "observation": "画面客观描述",
  "requirements": [
    {{"text": "红色雨伞", "category": "attribute", "criticality": "critical",
      "status": "satisfied", "evidence": "画面中央偏左有一把红色雨伞"}}
  ],
  "intent_alignment": 3,
  "subscores": {{
    "checks": {checks_example},
    "quality": {{
      "clarity": {{"score": 3, "reason": "清晰度良好"}},
      "artifacts": {{"score": 3, "reason": "左手手指数量异常"}},
      "text_render": {{"score": null, "reason": "画面无文字要求", "na": true}},
      "physics": {{"score": 3, "reason": "透视与光影合理"}},
      "consistency": {{"score": 3, "reason": "风格统一"}}
    }},
    "aesthetics": {{
      "composition": {{"score": 3, "reason": "构图稳定"}},
      "color": {{"score": 4, "reason": "配色和谐"}},
      "lighting": {{"score": 3, "reason": "光线自然"}},
      "texture": {{"score": 3, "reason": "质感一般"}},
      "appeal": {{"score": 3, "reason": "整体有吸引力"}}
    }}
  }},
  "notable_issues": ["左手手指异常"],
  "verdict": "一句话结论"
}}"""


CHECK_INSTRUCTIONS = """
额外强制细项检查：在 subscores 中添加 checks 数组，逐项包含下列 12 个 key，不可遗漏或重复：
{catalog}
每项结构：{{"key":"finger_count","status":"unassessable","location":"画面右侧人物的手","evidence":"手在口袋内，无法数清手指"}}。
status 只能为 pass / minor / major / severe / unassessable / not_applicable。
pass=可见且未发现缺陷；minor=局部轻微瑕疵；major=明确缺陷影响使用；severe=严重结构错误、主体不可用。
unassessable=相关部位存在但遮挡、手套、出画、分辨率或角度不足；not_applicable=图中没有该检查对象。
人体手指/手部/肢体/关节/面部/比例项只检查人或具有人体结构的角色；只有动物的图不能按人类五指标准扣分。
手指不全可见不能推断少指；只在能确认完整手掌、指根和指尖时判定数量。多人逐人区分，不把他人的手算到同一人。
尊重 Query 指定的卡通、夸张、非人形或特殊身体设定；身体差异本身不是生成缺陷。
location 指明画面方位、对象和部位；evidence 描述可见证据（例如右侧手清楚出现六个指尖），不得凭常识猜测。
不适用和不可判定也要写明原因。每项 evidence 尽量不超过 35 字。
如果指数量或结构有 major/severe，artifacts 不得给高分；可见严重缺陷将触发系统质量封顶，不能由漂亮光影抵消。
所有 12 项必须出现在 subscores.checks 中。只输出 JSON，所有字符串须正确转义。
"""


FEEDBACK_INSTRUCTIONS = """
先在顶层输出 quality_gate 对象：
{{"delivery":"minor_edits","required_edits":["定位具体需修改的内容；无需修改时用空数组"],"excellence":[]}}。
delivery: ready=无需修改可交付，minor_edits=需局部修改，major_edits=需大幅修改，unusable=需重新生成。
required_edits 只填写有图像证据的修改事项；不可为凑低评价编造问题。ready 时必须为空。
excellence 可以为空，不要为了达到两项门槛编造赞美。excellence 仅记录超出基本合格的优秀之处，最多 3 项，每项必须说明位置、特征和为什么突出；没有就填空数组。
然后在顶层增加 feedback 对象，这是展示给用户的主要评价，不得简单根据分数换算：
{{"rating":"满意","positive_points":["构图舒服"],"negative_points":[],"explanation":"结合原始需求和图中具体位置说明理由"}}。
满意度标准：{criteria}
positive_points 只允许从 {positive} 选择；negative_points 只允许从 {negative} 选择。
两类可同时多选，不可捏造不存在的优点或问题，不要输出未在选项中的标签。
只选择可见且有证据支持的项；遮挡或看不清不能判多指/少指，也不能据此声称手部自然。
没有人物时不选人物/手/面部/肢体相关项。文字无需出现时，不因为没有文字而选文字错误。
重大或严重缺陷、关键需求缺失时不能评为满意或非常满意；严重主体不可用选非常不满意。
explanation 必填，说明所选优缺点的可见位置和具体表现。非常满意/满意至少选一个满意点；不满意/非常不满意至少选一个不满意点。
严格复查步骤：
1. 先逐条核对所有原始需求，再审主体结构、手与关节连接、边缘接触、文字、材质与光照，最后看美学。禁止先因氛围好就决定高评价。
2. 对动作和场景做反事实核对：把用户场景换成普通室内人像/泛化观众席，把动作换成静止摆拍，如果画面仍同样成立且没有区分线索，就不能声称完整表达了指定场景或动作。动作和场景必须有具体线索。“有人+背景光斑”不足以自动证明演唱会；“手靠近围巾”不一定证明正在整理围巾。线索不充分时把该需求记为 partial 并解释缺什么，而非脑补 satisfied。
3. 用户要求的精确文字逐字核对；数量逐个数；主体与物体的接触关系要可信。不要把柔光、景深、暖色调、主体突出、皮肤纹理清晰、没有畸形等常见表现当作优秀证据。这些是合格要求，应支持满意而不是非常满意。优秀需体现有意图的视觉设计或有难度的细节执行，且不是一段通用赞美。
4. ready 只说明可交付，通常对应满意。非常满意还要求 excellence 至少两项来自不同方面，所有需求 satisfied，negative_points 与 notable_issues 均为空，且无 minor/major/severe 检查项。
5. minor_edits 最高一般；major_edits 或关键需求 missing/contradicted 最高不满意；unusable 必须非常不满意。任何需求 partial、missing 或 contradicted 都不能评价为满意或非常满意。
6. 不因用户没要求全身/手部可见而扣分；画外、自然遮挡和风格约定不是缺陷。不能确认的缺陷只写观察边界。真正优质的图可以获得高评价，不按比例强行分档，也不统一降低一档。
7. explanation 要明确交付判断及限制它获得更高档位的具体原因；最高档则解释可核实的突出之处。数值子项 3 为普通完成度、4 为良好、5 为有明确证据的优秀，不默认给 4/5。
已有数值子项保留用于诊断，用户主结论以这份结构化满意度评价为准。
"""


def _anchors_text(rubric: Rubric) -> str:
    return "\n".join(f"{score} = {text}" for score, text in sorted(rubric.anchors.items()))


def prompt_hash(rubric: Rubric) -> str:
    material = f"{PROMPT_VERSION}|{rubric.version}|{SYSTEM_TEMPLATE}|{CHECK_INSTRUCTIONS}|{CHECKS}|{CHECKLIST_VERSION}|{FEEDBACK_INSTRUCTIONS}|{RATING_CRITERIA}|{RATING_POLICY_VERSION}|{POSITIVE_POINTS}|{NEGATIVE_POINTS}|{_anchors_text(rubric)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_messages(query: str, image_data_url: str, rubric: Rubric) -> list[dict]:
    system = SYSTEM_TEMPLATE.format(anchors=_anchors_text(rubric), checks_example=json.dumps([{"key":key,"status":"unassessable","location":"请按实际图片填写位置","evidence":"请按实际图像判断状态并说明证据，不得照抄示例"} for key in CHECKS], ensure_ascii=False)) + CHECK_INSTRUCTIONS.format(catalog="\n".join(f"- {key}: {value}" for key, value in CHECKS.items()))
    system += FEEDBACK_INSTRUCTIONS.format(criteria=json.dumps(RATING_CRITERIA, ensure_ascii=False), positive=json.dumps(POSITIVE_POINTS, ensure_ascii=False), negative=json.dumps(NEGATIVE_POINTS, ensure_ascii=False))
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
