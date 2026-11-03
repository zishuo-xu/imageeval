import json
import httpx
import pytest
from imageeval.judge.base import SchemaJudgeError
from tests.helpers import valid_judge_payload
from tests.test_provider import _provider

@pytest.mark.parametrize('case', ['ordinary_top','top_with_minor','partial_requirement','needs_edits','major_edits','severe'])
async def test_high_rating_requires_delivery_evidence(case,rubric,make_image):
    data=valid_judge_payload()
    if case.startswith('top') or case=='ordinary_top':
        data['feedback']['rating']='非常满意'
    if case=='top_with_minor':
        data['quality_gate']['excellence']=['前景轮廓与背景层次分离精确','边缘玻璃折射细节丰富']
        data['subscores']['checks'][0]['status']='minor'
    if case=='partial_requirement':data['requirements'][0]['status']='partial'
    if case=='needs_edits':data['quality_gate'].update(delivery='minor_edits',required_edits=['修补右侧接缝'])
    if case=='major_edits':
        data['quality_gate'].update(delivery='major_edits',required_edits=['重绘主体'])
        data['feedback']['rating']='一般'
    if case=='severe':
        data['feedback'].update(rating='不满意',negative_points=['多肢体或少肢体'])
        data['subscores']['checks'][0]['status']='severe'
    provider=_provider(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]}),rubric)
    with pytest.raises(SchemaJudgeError):await provider.evaluate('人物',make_image())

async def test_excellent_visible_quality_allowed_without_penalizing_hidden_hands(rubric,make_image):
    data=valid_judge_payload()
    data['feedback']['rating']='非常满意'
    data['quality_gate']['excellence']=['主体与背景层次有清晰且有意图的安排','材质反光的细节与环境光一致且完成度突出']
    data['subscores']['checks'][0].update(status='unassessable',evidence='手被自然遮挡，不是缺陷')
    provider=_provider(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]}),rubric)
    result=await provider.evaluate('半身像',make_image())
    assert result.parsed.feedback.rating=='非常满意'

async def test_editable_draft_can_be_average(rubric,make_image):
    data=valid_judge_payload()
    data['feedback'].update(rating='一般',negative_points=['边缘伪影'])
    data['quality_gate'].update(delivery='minor_edits',required_edits=['修补主体右侧边缘的重影'])
    provider=_provider(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]}),rubric)
    assert (await provider.evaluate('人像',make_image())).parsed.feedback.rating=='一般'

async def test_json_mode_is_explicit_and_preserves_contract(rubric,make_image):
    requests=[]
    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(valid_judge_payload())}}]})
    provider=_provider(handler,rubric,json_mode=True,max_tokens=32768)
    await provider.evaluate('产品',make_image())
    assert requests[0]['response_format']=={'type':'json_object'}
    assert requests[0]['max_tokens']==32768
