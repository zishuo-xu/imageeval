from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AppConfig
from .db import Database, mark_stale_runs, migrate
from .importer import import_file
from .judge import build_provider
from .models import ReviewSubmit
from .pipeline import RunManager, execute_run
from .report import build_summary, export_static_report, render_report_html
from .review import counts, review_queue, submit_review
from .runs import create_run, get_run, list_runs
from .rubric.loader import Rubric, load_rubric
from .storage import ensure_data_dirs, resolve_under

WEB_DIR = Path(__file__).parent / "web"


class RunCreate(BaseModel):
    name: str
    batch_id: str


class ReportExportRequest(BaseModel):
    run_id: str


class _State:
    def __init__(self, cfg: AppConfig, provider=None):
        self.cfg = cfg
        self.provider = provider
        self.db: Database | None = None
        self.rubric: Rubric | None = None
        self.manager: RunManager | None = None


def create_app(cfg: AppConfig, provider=None) -> FastAPI:
    state = _State(cfg, provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_data_dirs(cfg)
        db = Database(cfg.db_path)
        migrate(db.conn)
        rubric = load_rubric(cfg.rubric_path)
        judge = provider or build_provider(cfg, rubric)
        mark_stale_runs(db)
        state.db = db
        state.rubric = rubric
        state.manager = RunManager(db, cfg, judge, rubric)
        app.state.state = state
        yield
        aclose = getattr(judge, "aclose", None)
        if aclose is not None:
            await aclose()
        db.close()

    app = FastAPI(title="imageeval", lifespan=lifespan)

    def db() -> Database:
        assert state.db is not None
        return state.db

    def rubric() -> Rubric:
        assert state.rubric is not None
        return state.rubric

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/import")
    async def api_import(
        file: UploadFile = File(...),
        image_root: str | None = Form(None),
        download: bool = Form(False),
    ) -> dict:
        suffix = Path(file.filename or "upload.csv").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            temp_path = Path(tmp.name)
        try:
            result = await run_in_threadpool(
                import_file,
                db(),
                cfg,
                temp_path,
                Path(image_root) if image_root else None,
                download,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "batch_id": result.batch_id,
            "imported": result.imported,
            "rejected": result.rejected,
            "report": result.report,
        }

    @app.get("/api/batches")
    def api_batches() -> list[dict]:
        return [dict(row) for row in db().query("SELECT * FROM import_batches ORDER BY created_at DESC")]

    @app.get("/api/batches/{batch_id}/report")
    def api_batch_report(batch_id: str) -> dict:
        row = db().query_one("SELECT * FROM import_batches WHERE id = ?", (batch_id,))
        if row is None:
            raise HTTPException(404, "batch not found")
        import json

        return {"batch": dict(row), "report": json.loads(row["report_json"] or "[]")}

    @app.get("/api/samples")
    def api_samples(
        run_id: str,
        state: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        rows = db().query(
            "SELECT s.*, e.status AS eval_status, st.state, e.overall_score, "
            "e.adherence_score, e.quality_score, e.aesthetics_score "
            "FROM samples s "
            "JOIN runs r ON r.batch_id = s.batch_id AND r.id = ? "
            "LEFT JOIN evaluations e ON e.sample_id = s.id AND e.run_id = r.id "
            "LEFT JOIN v_evaluation_state st ON st.id = e.id "
            "WHERE (? IS NULL OR st.state = ?) AND (? IS NULL OR s.query_text LIKE '%' || ? || '%') "
            "ORDER BY s.created_at LIMIT ? OFFSET ?",
            (run_id, state, state, q, q, limit, offset),
        )
        return {
            "items": [
                {
                    "sample_id": row["id"],
                    "external_id": row["external_id"],
                    "query": row["query_text"],
                    "state": row["state"],
                    "model_name": row["model_name"],
                    "thumb_url": f"/api/samples/{row['id']}/image?size=thumb",
                    "ai": {
                        "adherence": row["adherence_score"],
                        "quality": row["quality_score"],
                        "aesthetics": row["aesthetics_score"],
                        "overall": row["overall_score"],
                    },
                }
                for row in rows
            ]
        }

    @app.get("/api/samples/{sample_id}")
    def api_sample_detail(sample_id: str) -> dict:
        row = db().query_one("SELECT * FROM samples WHERE id = ?", (sample_id,))
        if row is None:
            raise HTTPException(404, "sample not found")
        import json

        return {
            **dict(row),
            "tags": json.loads(row["tags_json"] or "[]"),
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    @app.get("/api/samples/{sample_id}/image")
    def api_sample_image(sample_id: str, size: str = "orig") -> FileResponse:
        row = db().query_one(
            "SELECT image_path, thumb_path FROM samples WHERE id = ?", (sample_id,)
        )
        if row is None:
            raise HTTPException(404, "sample not found")
        use_thumb = size == "thumb" and row["thumb_path"]
        relative = row["thumb_path"] if use_thumb else row["image_path"]
        root = cfg.thumbs_dir if use_thumb else cfg.images_dir
        try:
            path = resolve_under(root, relative)
        except ValueError as exc:
            raise HTTPException(400, "invalid image path") from exc
        if not path.exists():
            raise HTTPException(404, "image not found")
        return FileResponse(path)

    @app.post("/api/runs")
    def api_create_run(body: RunCreate) -> dict:
        try:
            run_id = create_run(db(), cfg, rubric(), body.batch_id, body.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/runs")
    def api_list_runs(batch_id: str | None = None) -> list[dict]:
        return list_runs(db(), batch_id)

    @app.get("/api/runs/{run_id}")
    def api_get_run(run_id: str) -> dict:
        try:
            return {"run": get_run(db(), run_id), "counts": counts(db(), run_id)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/runs/{run_id}/start")
    async def api_start_run(run_id: str) -> dict:
        assert state.manager is not None
        existing = db().query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
        if existing is None:
            raise HTTPException(404, "run not found")
        if not state.manager.start(run_id):
            raise HTTPException(409, "run is already running")
        return {"ok": True}

    @app.post("/api/runs/{run_id}/pause")
    def api_pause_run(run_id: str) -> dict:
        assert state.manager is not None
        state.manager.pause(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/cancel")
    def api_cancel_run(run_id: str) -> dict:
        assert state.manager is not None
        state.manager.cancel(run_id)
        return {"ok": True}

    @app.post("/api/evaluations/{evaluation_id}/retry")
    async def api_retry_evaluation(evaluation_id: str) -> dict:
        row = db().query_one(
            "SELECT e.run_id FROM evaluations e WHERE e.id = ?", (evaluation_id,)
        )
        if row is None:
            raise HTTPException(404, "evaluation not found")
        db().execute("DELETE FROM evaluations WHERE id = ? AND status = 'error'", (evaluation_id,))
        run_id = row["run_id"]
        assert state.manager is not None
        state.manager.start(run_id)
        return {"ok": True}

    @app.get("/api/review/queue")
    def api_review_queue(
        run_id: str,
        filter: str = "pending",
        order: str = "default",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        try:
            return review_queue(db(), run_id, filter, order, limit, offset)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/evaluations/{evaluation_id}/review")
    def api_submit_review(evaluation_id: str, payload: ReviewSubmit) -> dict:
        try:
            return submit_review(db(), cfg, rubric(), evaluation_id, payload)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/reports/summary")
    def api_report_summary(run_id: str) -> dict:
        try:
            return build_summary(db(), run_id, rubric())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/report")
    def report_page(run_id: str) -> HTMLResponse:
        try:
            summary = build_summary(db(), run_id, rubric())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return HTMLResponse(render_report_html(summary, cfg.data_dir))

    @app.post("/api/reports/export")
    def api_export_report(body: ReportExportRequest) -> dict:
        try:
            summary = build_summary(db(), body.run_id, rubric())
            path = export_static_report(summary, cfg.data_dir, cfg.reports_dir)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"path": str(path), "url": f"/api/files/reports/{path.name}"}

    @app.get("/api/files/reports/{name}")
    def api_report_file(name: str) -> FileResponse:
        try:
            path = resolve_under(cfg.reports_dir, name)
        except ValueError as exc:
            raise HTTPException(400, "invalid file name") from exc
        if not path.exists():
            raise HTTPException(404, "file not found")
        return FileResponse(path)

    @app.get("/")
    def index_page() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
