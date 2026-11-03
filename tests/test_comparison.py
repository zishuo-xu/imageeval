import json
import uuid

import pytest
from pydantic import ValidationError

from imageeval.comparison import ComparisonVote, get_comparison, list_experiments, save_vote
from imageeval.generation import GenerationManager, GenerationRequest
from imageeval.judge.fake import FakeProvider
from imageeval.pipeline import _evaluate_one
from tests.test_generation import Generator, Runs


def ab_request(cfg, queries=None, n=1):
    queries = queries or ["一只猫"]
    expansion_id = uuid.uuid4()
    root = cfg.data_dir / "expansions"
    root.mkdir(exist_ok=True, parents=True)
    (root / f"{expansion_id}.json").write_text(json.dumps({"id":str(expansion_id), "model":"pe", "template_version":"v1", "parameters":{}, "items":[{"original_query":q,"expanded_prompt":q+"，柔光"} for q in queries]}))
    return GenerationRequest(request_id=uuid.uuid4(), prompts=[q+"，柔光" for q in queries], original_queries=queries,
                             expansion_id=expansion_id, images_per_prompt=n, ab_compare=True, auto_score=False)


@pytest.mark.asyncio
async def test_ab_pairs_original_scoring_vote_and_summary(db,cfg,rubric,make_image,monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY","test")
    calls=[]
    class Capturing(Generator):
        async def generate(self,prompt,n,ratio,directory):
            calls.append((prompt,n,ratio))
            return await super().generate(prompt,n,ratio,directory)
    manager=GenerationManager(cfg,db,rubric,Runs(),Capturing(make_image()))
    req=ab_request(cfg,["猫","狗"],2)
    job=manager.start(req)
    await manager.task
    assert job["total"] == 8
    assert calls == [("猫",2,"1:1"),("猫，柔光",2,"1:1"),("狗",2,"1:1"),("狗，柔光",2,"1:1")]
    manager.start(req)
    assert len(calls)==4
    samples=db.query("SELECT * FROM samples WHERE batch_id=?",(job["batch_id"],))
    assert len(samples)==8
    assert {s["query_text"] for s in samples}=={"猫","狗"}
    for sample in samples:
        await _evaluate_one(db,cfg,FakeProvider(),rubric,job["run_id"],sample)
    result=get_comparison(manager,db,req.request_id)
    assert result["summary"]["complete"]==result["summary"]["scored"]==4
    assert result["seed_controlled"] is False
    for pair in result["pairs"]:
        assert pair["A"]["prompt_expansion"]["mode"]=="direct"
        assert pair["B"]["prompt_expansion"]["mode"]=="pe"
    first=result["pairs"][0]
    db.execute("UPDATE evaluations SET status='error', overall_score=NULL WHERE sample_id=?",(first["B"]["sample_id"],))
    result=get_comparison(manager,db,req.request_id)
    assert result["summary"]["scored"]==3  # Missing/failed scores must not count as zero.
    save_vote(manager,db,req.request_id,"1-1",ComparisonVote(winner="B",note="细节更丰富"))
    save_vote(manager,db,req.request_id,"1-1",ComparisonVote(winner="tie",note="改为持平"))
    result=get_comparison(manager,db,req.request_id)
    assert result["summary"]["votes"]==result["summary"]["tie"]==1
    assert result["summary"]["B"]==0
    assert result["pairs"][0]["vote"]["note"]=="改为持平"
    assert list_experiments(manager)[0]["id"]==str(req.request_id)


@pytest.mark.asyncio
async def test_ab_partial_keeps_missing_pair_visible(db,cfg,rubric,make_image,monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY","test")
    manager=GenerationManager(cfg,db,rubric,Runs(),Generator(make_image(),fail_after=1))
    req=ab_request(cfg)
    manager.start(req)
    await manager.task
    result=get_comparison(manager,db,req.request_id)
    assert result["status"]=="partial"
    assert result["pairs"][0]["A"] is not None and result["pairs"][0]["B"] is None
    assert result["summary"]["complete"]==result["summary"]["scored"]==0
    assert result["summary"]["mean_delta"]["overall"] is None
    with pytest.raises(ValueError,match="齐全"):
        save_vote(manager,db,req.request_id,"1-1",ComparisonVote(winner="A"))
    with pytest.raises(LookupError):
        save_vote(manager,db,req.request_id,"missing",ComparisonVote(winner="A"))


def test_ab_requires_pe_and_caps_total(cfg):
    with pytest.raises(ValidationError):
        GenerationRequest(request_id=uuid.uuid4(),prompts=["猫"],ab_compare=True)
    req=ab_request(cfg,[f"猫{i}" for i in range(16)])
    assert len(req.prompts)==16
    with pytest.raises(ValidationError):
        ab_request(cfg,[f"猫{i}" for i in range(16)],2)


def test_ab_api_vote_export_and_restart(cfg,make_image,monkeypatch):
    from fastapi.testclient import TestClient
    from imageeval.api import create_app
    monkeypatch.setenv("MINIMAX_API_KEY","test")
    req=ab_request(cfg)
    with TestClient(create_app(cfg,provider=FakeProvider())) as client:
        manager=client.app.state.state.generation
        manager.generator=Generator(make_image())
        response=client.post("/api/generation",json=req.model_dump(mode="json"))
        assert response.status_code==202
        async def finish():
            await manager.task
        client.portal.call(finish)
        url=f"/api/comparisons/{req.request_id}"
        assert client.get(url).json()["summary"]["complete"]==1
        assert client.post(url+"/votes/1-1",json={"winner":"B","note":"人工测试选择"}).status_code==200
        save_vote(manager, client.app.state.state.db, req.request_id, "1-1", ComparisonVote(winner="B", note="历史选择"))
        exported=client.get(url+"/export")
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json()["pairs"][0]["vote"]["winner"]=="B"
        assert client.post(url+"/votes/1-1",json={"winner":"invalid"}).status_code==422
        assert client.get(f"/api/comparisons/{uuid.uuid4()}").status_code==404
    with TestClient(create_app(cfg,provider=FakeProvider())) as client:
        assert client.get(url).json()["summary"]["B"]==1
