"""Human preference labels, kept separate from numeric model scores."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator

RATINGS = ['非常满意', '满意', '一般', '不满意', '非常不满意']
POSITIVE_POINTS = ['符合提示词', '主体完整', '人物自然', '手部自然', '面部自然', '动作自然', '文字准确', '画面清晰', '构图舒服', '配色协调', '光影自然', '质感真实', '风格符合预期']
NEGATIVE_POINTS = ['偏离提示词', '主体缺失', '主体数量错误', '多手指', '少手指', '手指粘连或扭曲', '多肢体或少肢体', '关节连接异常', '面部异常', '身体比例异常', '文字错误', '画面模糊', '边缘伪影', '遮挡关系错误', '光影不合理', '构图不佳', '颜色不协调', '质感失真', '风格不符', '场景表达不足', '动作表达不足', '细节完成度不足']

class Feedback(BaseModel):
    rating: Literal['非常满意', '满意', '一般', '不满意', '非常不满意']
    positive_points: list[str] = Field(default_factory=list, max_length=len(POSITIVE_POINTS))
    negative_points: list[str] = Field(default_factory=list, max_length=len(NEGATIVE_POINTS))

    explanation: str = Field(default="", max_length=800)

    @model_validator(mode='after')
    def known_points(self):
        for values, allowed in [(self.positive_points, POSITIVE_POINTS), (self.negative_points, NEGATIVE_POINTS)]:
            if len(values) != len(set(values)) or not set(values) <= set(allowed):
                raise ValueError('反馈点包含重复或未知选项')
        return self

RATING_CRITERIA = {
    '非常满意': '达到优秀交付质量：所有明确需求成立，无已发现的问题，无需修改；除基本合格外，至少两项不同方面的表现突出，并能定位到画面证据。主体存在、清晰或普通好看不构成优秀。',
    '满意': '达到交付质量：全部明确需求满足，主体和细节可信，无需修补即可使用；整体稳妥但没有足够证据证明优秀。',
    '一般': '方向正确但仅达到初稿质量：部分需求表达不足、动作或场景证据弱，或存在需修补的可见局部问题；修改后才能交付。',
    '不满意': '存在明确关键需求失败、畸形、指定文字错误或明显结构问题，需要较大修改；好看的配色和光影不能抵消这些问题。',
    '非常不满意': '主体或关键语义根本错误、严重结构崩坏，整体无法使用，需要重新生成。',
}

RATING_POLICY_VERSION = 'strict-v1'
