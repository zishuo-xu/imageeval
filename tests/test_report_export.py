from imageeval.models import ReviewSubmit
from imageeval.report import build_summary, export_static_report
from imageeval.review import submit_review
from imageeval.runs import create_run
from tests.test_report import _add_eval


def test_export_static_report_inlines_images(db, cfg, rubric, seed_batch) -> None:
    batch_id, sample_ids = seed_batch(1)
    run_id = create_run(db, cfg, rubric, batch_id, "静态报告")
    eval_id = _add_eval(db, run_id, sample_ids[0], (2, 2, 2))
    submit_review(
        db,
        cfg,
        rubric,
        eval_id,
        ReviewSubmit(decision="corrected", human_adherence=1, human_quality=2, human_aesthetics=2),
    )

    summary = build_summary(db, run_id, rubric)
    path = export_static_report(summary, cfg.data_dir, cfg.reports_dir)

    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "data:image/jpeg;base64," in html
    assert "/api/samples/" not in html
    assert "window.__REPORT_DATA__" in html
