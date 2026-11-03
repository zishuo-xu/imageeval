import json
import httpx
import pytest
from pydantic import ValidationError
from imageeval.feedback import Feedback, RATINGS
from imageeval.models import ReviewSubmit
from imageeval.review import submit_review, review_queue
from imageeval.report import build_summary
from imageeval.export import export_dataset
from imageeval.judge.base import SchemaJudgeError
from tests.test_review import _seed_run
from tests.test_provider import _provider
from tests.helpers import valid_judge_payload

@pytest.mark.parametrize('rating', RATINGS)
def test_feedback_roundtrip_export_report(rating, db, cfg, rubric, seed_batch):
    run, _, evals = _seed_run(db, cfg, rubric, seed_batch)
    feedback = Feedback(rating=rating, positive_points=['构图舒服'], negative_points=['多手指'])
    submit_review(db, cfg, rubric, evals[0], ReviewSubmit(decision='rated', feedback=feedback, note='右手有六个指尖'))
    item = review_queue(db, run, 'reviewed')['items'][0]
    assert item['state'] == 'rated'
    assert item['human']['feedback'] == feedback.model_dump()
    assert item['human']['overall'] is None
    assert review_queue(db, run, 'pending')['total'] == 1
    summary = build_summary(db, run, rubric)
    assert summary['counts']['reviewed'] == 1
    assert summary['feedback']['human']['ratings'][rating] == 1
    assert summary['feedback']['human']['negative_points']['多手指'] == 1
    assert summary['agreement']['n'] == 0
    path = export_dataset(db, cfg, run, 'sft')
    record = json.loads((path/'dataset.jsonl').read_text().splitlines()[0])
    assert record['label_type'] == 'satisfaction'
    assert record['meta']['note'] == '右手有六个指尖'
    assert record['label'] == feedback.model_dump()
    raw = export_dataset(db, cfg, run, 'only-reviewed')
    record = json.loads((raw/'dataset.jsonl').read_text().splitlines()[0])
    assert record['final']['scores'] is None
    assert record['final']['feedback'] == feedback.model_dump()

@pytest.mark.parametrize('kwargs', [dict(rating='满分'),dict(rating='满意',positive_points=['乱写']),dict(rating='一般',negative_points=['多手指','多手指'])])
def test_invalid_feedback_rejected(kwargs):
    with pytest.raises(ValidationError): Feedback(**kwargs)

def test_rating_is_required_and_not_numeric():
    with pytest.raises(ValidationError): ReviewSubmit(decision='rated')
    with pytest.raises(ValidationError): ReviewSubmit(decision='rated', feedback=Feedback(rating='一般'), human_quality=3)

@pytest.mark.parametrize('missing', ['feedback', 'explanation', 'contradiction'])
async def test_ai_requires_evidence_and_consistency(missing, rubric, make_image):
    payload = valid_judge_payload()
    if missing == 'feedback': payload.pop('feedback')
    elif missing == 'explanation': payload['feedback']['explanation']=''
    else: payload['subscores']['checks'][0]['status']='major'
    provider = _provider(lambda _: httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(payload)}}]}),rubric)
    with pytest.raises(SchemaJudgeError): await provider.evaluate('人物',make_image())


def test_unreviewed_export_uses_ai_feedback(db, cfg, rubric, seed_batch):
    run, _, evals = _seed_run(db, cfg, rubric, seed_batch)
    feedback = Feedback(rating='不满意',negative_points=['文字错误'],explanation='招牌文字错误').model_dump()
    db.execute('UPDATE evaluations SET subscores_json=? WHERE id=?',(json.dumps({'feedback':feedback}),evals[0]))
    output = export_dataset(db,cfg,run,'raw')
    rows=[json.loads(line) for line in (output/'dataset.jsonl').read_text().splitlines()]
    item=next(row for row in rows if row['ai']['feedback'])
    assert item['final']['feedback']==feedback
    assert item['final']['scores'] is None
    assert item['final']['source']=='ai'
