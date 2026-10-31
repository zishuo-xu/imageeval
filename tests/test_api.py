import asyncio
import io
import time

from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def _client(cfg, provider=None):
    app = create_app(cfg, provider=provider or FakeProvider())
    return TestClient(app)


def _import_csv(client: TestClient, make_image, tmp_path) -> str:
    image = make_image("api.png", (64, 64))
    csv_bytes = (
        "external_id,query,image,model_name\n"
        f"e1,一只红猫,{image.name},m1\n"
        f"e2,一只蓝狗,{image.name},m1\n"
    ).encode("utf-8")
    response = client.post(
        "/api/import",
        files={"file": ("data.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"image_root": str(image.parent)},
    )
    assert response.status_code == 200, response.text
    return response.json()["batch_id"]


def test_full_api_flow(cfg, make_image) -> None:
    with _client(cfg) as client:
        batch_id = _import_csv(client, make_image, None)

        batches = client.get("/api/batches").json()
        assert batches[0]["id"] == batch_id
        assert batches[0]["sample_count"] == 2

        run_response = client.post(
            "/api/runs", json={"name": "api run", "batch_id": batch_id}
        )
        assert run_response.status_code == 200, run_response.text
        run_id = run_response.json()["run_id"]

        start = client.post(f"/api/runs/{run_id}/start")
        assert start.status_code == 200, start.text

        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] in ("completed", "cancelled"):
                break
            time.sleep(0.1)
        assert run["status"] == "completed"

        queue = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "pending"}
        ).json()
        assert queue["total"] == 2
        item = queue["items"][0]

        review = client.post(
            f"/api/evaluations/{item['evaluation_id']}/review",
            json={"decision": "accepted"},
        )
        assert review.status_code == 200, review.text

        summary = client.get("/api/reports/summary", params={"run_id": run_id}).json()
        assert summary["counts"]["accepted"] == 1
        assert summary["counts"]["ai_done"] == 1

        html = client.get("/report", params={"run_id": run_id})
        assert html.status_code == 200
        assert "window.__REPORT_DATA__" in html.text

        image = client.get(f"/api/samples/{item['sample_id']}/image")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")


def test_unknown_run_returns_404(cfg) -> None:
    with _client(cfg) as client:
        assert client.get("/api/runs/nope").status_code == 404
        assert client.get("/api/reports/summary", params={"run_id": "nope"}).status_code == 404


def test_invalid_review_returns_422(cfg, make_image) -> None:
    with _client(cfg) as client:
        batch_id = _import_csv(client, make_image, None)
        run_id = client.post(
            "/api/runs", json={"name": "r", "batch_id": batch_id}
        ).json()["run_id"]
        client.post(f"/api/runs/{run_id}/start")
        for _ in range(50):
            if client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "completed":
                break
            time.sleep(0.1)
        item = client.get(
            "/api/review/queue", params={"run_id": run_id}
        ).json()["items"][0]

        bad = client.post(
            f"/api/evaluations/{item['evaluation_id']}/review",
            json={"decision": "corrected", "human_adherence": 4},
        )
        assert bad.status_code == 422


def test_import_unsupported_suffix_returns_400(cfg) -> None:
    with _client(cfg) as client:
        response = client.post(
            "/api/import",
            files={"file": ("data.txt", io.BytesIO(b"a,b\n1,2\n"), "text/plain")},
        )
        assert response.status_code == 400


def test_retry_non_error_returns_409(cfg, make_image) -> None:
    with _client(cfg) as client:
        batch_id = _import_csv(client, make_image, None)
        run_id = client.post(
            "/api/runs", json={"name": "r", "batch_id": batch_id}
        ).json()["run_id"]
        client.post(f"/api/runs/{run_id}/start")
        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "completed":
                break
            time.sleep(0.1)

        items = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "all"}
        ).json()["items"]
        item = next(i for i in items if i["state"] == "ai_done")

        retry = client.post(f"/api/evaluations/{item['evaluation_id']}/retry")
        assert retry.status_code == 409

        after = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "all"}
        ).json()["items"]
        still = next(i for i in after if i["evaluation_id"] == item["evaluation_id"])
        assert still["state"] == "ai_done"


def test_retry_error_after_completion_requeues(cfg, make_image) -> None:
    with _client(cfg, FakeProvider(fail_times=3)) as client:
        image = make_image("retry.png", (64, 64))
        csv_bytes = (
            "external_id,query,image,model_name\n"
            f"e1,一只红猫,{image.name},m1\n"
        ).encode("utf-8")
        response = client.post(
            "/api/import",
            files={"file": ("data.csv", io.BytesIO(csv_bytes), "text/csv")},
            data={"image_root": str(image.parent)},
        )
        assert response.status_code == 200, response.text
        batch_id = response.json()["batch_id"]
        run_id = client.post(
            "/api/runs", json={"name": "retry", "batch_id": batch_id}
        ).json()["run_id"]

        client.post(f"/api/runs/{run_id}/start")
        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "completed":
                break
            time.sleep(0.1)

        items = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "all"}
        ).json()["items"]
        assert len(items) == 1
        assert items[0]["state"] == "error"

        retry = client.post(f"/api/evaluations/{items[0]['evaluation_id']}/retry")
        assert retry.status_code == 200, retry.text

        requeued = False
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] == "completed":
                items = client.get(
                    "/api/review/queue", params={"run_id": run_id, "filter": "all"}
                ).json()["items"]
                if items and items[0]["state"] == "ai_done":
                    requeued = True
                    break
            time.sleep(0.1)
        assert requeued
        assert items[0]["ai"]["error"] is None
        assert items[0]["ai"]["parse_attempts"] == 1


def test_retry_unknown_evaluation_returns_404(cfg) -> None:
    with _client(cfg) as client:
        assert client.post("/api/evaluations/nope/retry").status_code == 404


class _SlowProvider(FakeProvider):
    async def evaluate(self, query, image_path):
        await asyncio.sleep(1.0)
        return await super().evaluate(query, image_path)


def test_retry_while_run_running_returns_409(cfg, make_image) -> None:
    with _client(cfg, _SlowProvider()) as client:
        batch_id = _import_csv(client, make_image, None)
        run_id = client.post(
            "/api/runs", json={"name": "running", "batch_id": batch_id}
        ).json()["run_id"]

        state = client.app.state.state
        sample_id = state.db.query_one(
            "SELECT id FROM samples WHERE batch_id = ?", (batch_id,)
        )["id"]
        state.db.execute(
            "INSERT INTO evaluations (id, sample_id, run_id, status, error, created_at) "
            "VALUES ('eval-error', ?, ?, 'error', 'boom', 'now')",
            (sample_id, run_id),
        )

        client.post(f"/api/runs/{run_id}/start")
        retry = client.post("/api/evaluations/eval-error/retry")
        assert retry.status_code == 409

        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["run"]["status"] not in (
                "running",
                "paused",
            ):
                break
            time.sleep(0.1)
