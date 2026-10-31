import io
import time

import pytest
from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def test_end_to_end_import_score_review_report_export(cfg, make_image) -> None:
    image = make_image("e2e.png", (96, 96))
    csv_bytes = (
        "external_id,query,image,model_name,tags\n"
        f"e1,一只红色的猫,{image.name},m1,a;b\n"
        f"e2,一只蓝色的狗,{image.name},m1,c\n"
    ).encode("utf-8")

    app = create_app(cfg, provider=FakeProvider(adherence=3, quality=3, aesthetics=4))
    with TestClient(app) as client:
        imported = client.post(
            "/api/import",
            files={"file": ("e2e.csv", io.BytesIO(csv_bytes), "text/csv")},
            data={"image_root": str(image.parent)},
        )
        assert imported.status_code == 200, imported.text
        batch_id = imported.json()["batch_id"]

        run_id = client.post(
            "/api/runs", json={"name": "e2e", "batch_id": batch_id}
        ).json()["run_id"]
        assert client.post(f"/api/runs/{run_id}/start").status_code == 200

        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] == "completed":
                break
            time.sleep(0.1)
        assert run["status"] == "completed"
        assert run["done"] == 2

        queue = client.get(
            "/api/review/queue", params={"run_id": run_id, "filter": "pending"}
        ).json()
        for item in queue["items"]:
            response = client.post(
                f"/api/evaluations/{item['evaluation_id']}/review",
                json={
                    "decision": "corrected",
                    "human_adherence": 2,
                    "human_quality": 3,
                    "human_aesthetics": 4,
                    "note": "端到端",
                    "duration_ms": 1200,
                },
            )
            assert response.status_code == 200, response.text

        summary = client.get("/api/reports/summary", params={"run_id": run_id}).json()
        assert summary["counts"]["reviewed"] == 2
        assert summary["acceptance_rate"] == 0.0
        assert summary["agreement"]["mae"]["adherence"] == pytest.approx(2.5)

        report = client.post("/api/reports/export", json={"run_id": run_id})
        assert report.status_code == 200
        report_url = report.json()["url"]
        assert client.get(report_url).status_code == 200

        dataset = client.post(
            "/api/exports/dataset", json={"run_id": run_id, "mode": "sft"}
        )
        assert dataset.status_code == 200, dataset.text
        assert dataset.json()["count"] == 2
        assert client.get(dataset.json()["url"]).status_code == 200
