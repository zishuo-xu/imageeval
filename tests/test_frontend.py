from fastapi.testclient import TestClient

from imageeval.api import create_app
from imageeval.judge.fake import FakeProvider


def test_index_and_static_assets(cfg) -> None:
    app = create_app(cfg, provider=FakeProvider())
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        for marker in (
            "btn-accept",
            "requirements",
            "image",
            "run-select",
            "btn-retry",
            "error-banner",
            'value="error"',
            "reason-general",
        ):
            assert marker in index.text
        for script in ("/static/api.js", "/static/app.js", "/static/review.js"):
            assert script in index.text

        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "--accent" in css.text

        js = client.get("/static/review.js")
        assert js.status_code == 200
        assert "loadQueue" in js.text
        assert "retryEvaluation" in js.text
        assert "escapeHtml(value.reason" in js.text
        assert "prefill(" in js.text
        assert "Math.round(ai)" in js.text
