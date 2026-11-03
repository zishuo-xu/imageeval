import json

import httpx
import pytest
from pydantic import ValidationError

from imageeval.models import JudgeOutput
from imageeval.scoring import compute_scores
from imageeval.judge.openai_compat import OpenAICompatProvider
from imageeval.config import JudgeConfig
from imageeval.judge.base import SchemaJudgeError
from tests.helpers import valid_judge_payload


@pytest.mark.parametrize("status,expected",[("severe",2),("major",3),("minor",4),("pass",5),("unassessable",5),("not_applicable",5)])
def test_visible_defect_caps_quality_but_occlusion_does_not(status,expected,rubric):
    payload=valid_judge_payload(5)
    payload["subscores"]["checks"][0].update(status=status,location="右侧手",evidence="可见证据或遮挡说明")
    scores=compute_scores(JudgeOutput.model_validate(payload),rubric)
    assert scores.quality==expected
    assert scores.aesthetics==5


def test_reject_duplicate_missing_and_unknown_check_keys():
    payload=valid_judge_payload()
    payload["subscores"]["checks"][-1]=payload["subscores"]["checks"][0]
    with pytest.raises(ValidationError): JudgeOutput.model_validate(payload)
    payload=valid_judge_payload()
    payload["subscores"]["checks"].pop()
    with pytest.raises(ValidationError): JudgeOutput.model_validate(payload)
    payload=valid_judge_payload()
    payload["subscores"]["checks"][0]["key"]="guess"
    with pytest.raises(ValidationError): JudgeOutput.model_validate(payload)


@pytest.mark.asyncio
async def test_real_provider_requires_checklist_not_silent_legacy_success(rubric,make_image):
    payload=valid_judge_payload()
    payload["subscores"].pop("checks")
    def handler(request):
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(payload)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=OpenAICompatProvider(JudgeConfig(base_url="https://test.invalid/v1",model="vision"),rubric,client)
        with pytest.raises(SchemaJudgeError,match="12 visual checks"):
            await provider.evaluate("人像",make_image())


def test_upgrade_keeps_old_run_and_uses_same_images(cfg,seed_batch,db,rubric):
    from fastapi.testclient import TestClient
    from imageeval.api import create_app
    from imageeval.judge.fake import FakeProvider
    from imageeval.runs import create_run
    batch,_=seed_batch(1)
    old=create_run(db,cfg,rubric,batch,"旧评测")
    db.execute("UPDATE runs SET prompt_hash='old-prompt' WHERE id=?",(old,))
    with TestClient(create_app(cfg,provider=FakeProvider())) as client:
        assert client.post(f"/api/runs/{old}/start",json={}).status_code==409
        new=client.post(f"/api/runs/{old}/upgrade",json={}).json()["run_id"]
        old_run=client.get(f"/api/runs/{old}").json()["run"]
        new_run=client.get(f"/api/runs/{new}").json()["run"]
    assert old_run["prompt_hash"]=="old-prompt"
    assert new_run["batch_id"]==old_run["batch_id"]
    assert json.loads(new_run["params_json"])["checklist_version"]=="visual-v2"


@pytest.mark.asyncio
async def test_truncated_output_has_explicit_error(rubric,make_image):
    from imageeval.judge.base import FatalJudgeError
    def handler(request):
        return httpx.Response(200,json={"choices":[{"finish_reason":"length","message":{"content":"{\"subscores\":"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=OpenAICompatProvider(JudgeConfig(base_url="https://test.invalid/v1",model="vision"),rubric,client)
        with pytest.raises(FatalJudgeError,match="max_tokens"):
            await provider.evaluate("人像",make_image())
