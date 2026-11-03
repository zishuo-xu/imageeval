import asyncio
import json
import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.generation import GenerationManager, GenerationRequest, GenerationError, MiniMaxGenerator
from imageeval.judge.fake import FakeProvider


class Generator:
    def __init__(self, image, fail_after=None):
        self.image, self.fail_after, self.calls = image, fail_after, 0

    async def generate(self, prompt, n, ratio, directory):
        self.calls += 1
        await asyncio.sleep(.01)
        if self.fail_after and self.calls > self.fail_after:
            raise GenerationError("quota exceeded")
        return [{"path": str(self.image), "request_id": "upstream-id", "latency_ms": 12} for _ in range(n)]


class Runs:
    def __init__(self):
        self.started = []

    def start(self, run_id):
        self.started.append(run_id)
        return True


def request(**kwargs):
    return GenerationRequest(request_id=uuid.uuid4(), prompts=["原始中文提示词"], **kwargs)


@pytest.mark.asyncio
async def test_generate_import_run_and_idempotency(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    gen = Generator(make_image())
    runs = Runs()
    manager = GenerationManager(cfg, db, rubric, runs, gen)
    req = request(images_per_prompt=2)
    job = manager.start(req)
    assert manager.start(req)["id"] == job["id"]
    await manager.task
    result = manager.get(req.request_id)
    assert result["status"] == "completed"
    assert result["generated"] == result["imported"] == 2
    assert runs.started == [result["run_id"]]
    assert gen.calls == 1
    samples = db.query("SELECT * FROM samples WHERE batch_id=?", (result["batch_id"],))
    assert {s["query_text"] for s in samples} == {"原始中文提示词"}
    assert {s["model_name"] for s in samples} == {"image-01"}
    assert json.loads(samples[0]["metadata_json"])["prompt_optimizer"] is False
    manager.start(req)
    assert gen.calls == 1
    assert "test-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_partial_failure_keeps_successful_images(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    gen = Generator(make_image(), fail_after=1)
    manager = GenerationManager(cfg, db, rubric, Runs(), gen)
    req = GenerationRequest(request_id=uuid.uuid4(), prompts=["一", "二", "三"])
    manager.start(req)
    await manager.task
    result = manager.get(req.request_id)
    assert result["status"] == "partial"
    assert result["imported"] == 1
    assert result["error"] == "quota exceeded"
    assert gen.calls == 2  # Do not retry or spend more after quota failure.


@pytest.mark.asyncio
async def test_busy_and_changed_request_rejected(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    manager = GenerationManager(cfg, db, rubric, Runs(), Generator(make_image()))
    req = request()
    manager.start(req)
    with pytest.raises(ValueError, match="已有"):
        manager.start(request())
    with pytest.raises(ValueError, match="不同"):
        manager.start(req.model_copy(update={"name": "different"}))
    await manager.task


def test_generation_validation_and_missing_key(cfg, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with TestClient(create_app(cfg, provider=FakeProvider())) as client:
        assert client.get("/api/generation/config").json()["configured"] is False
        req = request().model_dump(mode="json")
        assert client.post("/api/generation", json=req).status_code == 409
        req["prompts"] = ["x"] * 5
        req["images_per_prompt"] = 4
        assert client.post("/api/generation", json=req).status_code == 422
        req["prompts"] = [" "]
        assert client.post("/api/generation", json=req).status_code == 422
        assert client.get("/api/generation/invalid-path").status_code == 422


@pytest.mark.asyncio
async def test_provider_contract_and_http200_error(cfg, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    image = make_image().read_bytes()
    requests = []
    async def handler(req):
        requests.append(req)
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["prompt_optimizer"] is False
            assert body["prompt"] == "原始提示词"
            assert req.headers["authorization"] == "Bearer test-secret"
            return httpx.Response(200, json={"base_resp": {"status_code": 0}, "id": "id", "data": {"image_urls": ["https://image.test/1"]}})
        assert "authorization" not in req.headers
        return httpx.Response(200, content=image)
    client_class = httpx.AsyncClient
    monkeypatch.setattr("imageeval.generation.httpx.AsyncClient", lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw))
    gen = MiniMaxGenerator(cfg.generation)
    result = await gen.generate("原始提示词", 1, "1:1", cfg.data_dir / "probe")
    assert len(result) == 1
    assert len(requests) == 2
    async def failure(req):
        return httpx.Response(200, json={"base_resp": {"status_code": 1008, "status_msg": "test-secret"}})
    monkeypatch.setattr("imageeval.generation.httpx.AsyncClient", lambda **kw: client_class(transport=httpx.MockTransport(failure), **kw))
    with pytest.raises(GenerationError, match="1008") as error:
        await gen.generate("原始提示词", 1, "1:1", cfg.data_dir / "failed")
    assert "test-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_interruption_is_persisted_without_regeneration(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    class SlowGenerator(Generator):
        async def generate(self, *args):
            self.calls += 1
            await asyncio.sleep(60)
    generator = SlowGenerator(make_image())
    manager = GenerationManager(cfg, db, rubric, Runs(), generator)
    req = request()
    manager.start(req)
    await asyncio.sleep(.01)
    await manager.close()
    assert manager.get(req.request_id)["status"] == "interrupted"
    restored = GenerationManager(cfg, db, rubric, Runs(), generator)
    assert restored.latest()["status"] == "interrupted"
    restored.start(req)
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_no_autoscore_creates_pending_run(db, cfg, rubric, make_image, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret")
    runs = Runs()
    manager = GenerationManager(cfg, db, rubric, runs, Generator(make_image()))
    req = request(auto_score=False)
    manager.start(req)
    await manager.task
    result = manager.get(req.request_id)
    assert result["run_id"]
    assert runs.started == []
    assert db.query_one("SELECT status FROM runs WHERE id=?", (result["run_id"],))["status"] == "pending"


def test_workspace_assets_never_reuse_stale_conditional_cache(cfg):
    with TestClient(create_app(cfg, provider=FakeProvider())) as client:
        for path in ("/", "/static/generation.js"):
            first = client.get(path)
            assert first.headers["cache-control"] == "no-store"
            second = client.get(path, headers={"If-None-Match": first.headers["etag"]})
            assert second.status_code == 200
            assert second.headers["cache-control"] == "no-store"
