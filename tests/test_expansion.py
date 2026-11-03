import json
import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.config import JudgeConfig
from imageeval.expansion import ExpansionRequest, expand_prompts
from imageeval.generation import GenerationManager, GenerationRequest
from imageeval.judge.fake import FakeProvider
from imageeval.pipeline import _evaluate_one
from imageeval.export import export_dataset
from tests.test_generation import Generator, Runs


@pytest.mark.asyncio
async def test_expansion_preserves_order_and_records_model(cfg, monkeypatch):
    monkeypatch.setenv("PE_KEY", "private-test-value")
    cfg = replace(cfg, pe=JudgeConfig(base_url="https://pe.test/v1", model="pe-test", api_key_env="PE_KEY", max_tokens=800))
    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "pe-test"
        query = body["messages"][-1]["content"]
        return httpx.Response(200, json={"choices":[{"message":{"content":query+"，自然光"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await expand_prompts(cfg, ExpansionRequest(queries=["猫", "小屋"]), client)
    assert [i["original_query"] for i in result["items"]] == ["猫", "小屋"]
    assert result["items"][0]["expanded_prompt"] == "猫，自然光"
    assert result["parameters"]["max_tokens"] == 800
    saved = (cfg.data_dir / "expansions" / f"{result['id']}.json").read_text()
    assert "private-test-value" not in saved
    assert json.loads(saved) == result


@pytest.mark.asyncio
async def test_expansion_partial_errors_no_automatic_retry(cfg, monkeypatch):
    monkeypatch.setenv("IMAGEEVAL_API_KEY", "key")
    cfg = replace(cfg, judge=JudgeConfig(base_url="https://pe.test/v1", model="pe"))
    calls = []
    def handler(req):
        query = json.loads(req.content)["messages"][-1]["content"]
        calls.append(query)
        if query == "限流": return httpx.Response(429, text="secret upstream text")
        return httpx.Response(200,json={"choices":[{"message":{"content":"一段未完成文本"},"finish_reason":"length"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await expand_prompts(cfg, ExpansionRequest(queries=["限流","截断"]), client)
    assert len(calls) == 2
    assert all(i["error"] and i["expanded_prompt"] is None for i in result["items"])
    assert "secret upstream text" not in json.dumps(result)


@pytest.mark.asyncio
async def test_pe_generation_judges_original_and_exports_provenance(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "key")
    expansion_id = str(uuid.uuid4())
    root = cfg.data_dir / "expansions"
    root.mkdir(parents=True)
    (root / f"{expansion_id}.json").write_text(json.dumps({"id":expansion_id,"model":"pe-model","template_version":"pe-v1","parameters":{"temperature":0.2},"items":[{"original_query":"一只猫","expanded_prompt":"窗台上的一只猫","latency_ms":10,"usage":{"completion_tokens":10}}]}))
    class CapturingGenerator(Generator):
        async def generate(self, prompt, *args):
            assert prompt == "窗台上的一只橘猫"
            return await super().generate(prompt, *args)
    manager = GenerationManager(cfg, db, rubric, Runs(), CapturingGenerator(make_image()))
    req = GenerationRequest(request_id=uuid.uuid4(), prompts=["窗台上的一只橘猫"], original_queries=["一只猫"], expansion_id=expansion_id, auto_score=False)
    manager.start(req)
    await manager.task
    job = manager.get(req.request_id)
    assert job["status"] == "completed"
    sample = db.query_one("SELECT * FROM samples WHERE batch_id=?", (job["batch_id"],))
    assert sample["query_text"] == "一只猫"
    provenance = json.loads(sample["metadata_json"])["prompt_expansion"]
    assert provenance["edited"] is True
    assert provenance["generation_prompt"] == "窗台上的一只橘猫"
    assert provenance["expanded_prompt"] == "窗台上的一只猫"
    class Judge(FakeProvider):
        async def evaluate(self, query, image_path):
            assert query == "一只猫"
            return await super().evaluate(query, image_path)
    await _evaluate_one(db, cfg, Judge(), rubric, job["run_id"], sample)
    out = export_dataset(db,cfg,job["run_id"],"raw")
    record = json.loads((out / "dataset.jsonl").read_text().splitlines()[0])
    assert record["query"] == "一只猫"
    assert record["prompt_expansion"] == provenance
    bad = req.model_copy(update={"request_id":uuid.uuid4(),"original_queries":["两只猫"]})
    with pytest.raises(ValueError, match="错配"):
        manager.start(bad)


def test_pe_missing_configuration_and_invalid_alignment(cfg):
    with TestClient(create_app(cfg, provider=FakeProvider())) as client:
        assert client.post("/api/expansion", json={"queries":[]}).status_code == 422
        assert client.post("/api/expansion", json={"queries":["猫"]}).status_code == 400
        assert client.post("/api/generation", json={"request_id":str(uuid.uuid4()),"prompts":["猫"],"original_queries":["猫","狗"]}).status_code == 422
