from imageeval.report import build_summary, render_report_html
from imageeval.review import submit_review
from imageeval.models import ReviewSubmit
from imageeval.runs import create_run


def test_render_report_html_inlines_assets(db, cfg, rubric, seed_batch) -> None:
    from tests.test_report import _add_eval

    batch_id, sample_ids = seed_batch(1)
    run_id = create_run(db, cfg, rubric, batch_id, "报告测试")
    eval_id = _add_eval(db, run_id, sample_ids[0], (4, 4, 4))
    submit_review(db, cfg, rubric, eval_id, ReviewSubmit(decision="accepted"))

    summary = build_summary(db, run_id, rubric)
    html = render_report_html(summary, cfg.data_dir)

    assert "报告测试" in html
    assert "window.__REPORT_DATA__" in html
    assert "Chart" in html
    assert "{{" not in html
    assert "<style>" in html
