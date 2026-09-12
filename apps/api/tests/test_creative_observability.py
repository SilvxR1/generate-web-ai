"""app.creative.observability — P2 Part J: verifies pipeline-stage
logging fires with the documented fields and correctly reports
success/failure, without leaking exception content."""

import logging

from app.creative.observability import StageTimer, log_pipeline_stage


def test_log_pipeline_stage_emits_structured_record(caplog):
    with caplog.at_level(logging.INFO, logger="app.creative.pipeline"):
        log_pipeline_stage(stage="create_directions", business_id="b1", provider="higgsfield", result="success")

    [record] = caplog.records
    assert record.pipeline["stage"] == "create_directions"
    assert record.pipeline["business_id"] == "b1"
    assert record.pipeline["result"] == "success"


def test_stage_timer_marks_success_by_default(caplog):
    with caplog.at_level(logging.INFO, logger="app.creative.pipeline"):
        with StageTimer(stage="frontend_generate", business_id="b1", provider="anthropic"):
            pass

    [record] = caplog.records
    assert record.pipeline["result"] == "success"
    assert record.pipeline["duration_ms"] >= 0


def test_stage_timer_logs_failure_on_exception_without_leaking_its_message(caplog):
    with caplog.at_level(logging.WARNING, logger="app.creative.pipeline"):
        try:
            with StageTimer(stage="generative_build", business_id="b1", provider="anthropic"):
                raise RuntimeError("some provider response containing sensitive detail")
        except RuntimeError:
            pass

    [record] = caplog.records
    assert record.pipeline["result"] == "failure"
    assert "sensitive detail" not in record.getMessage()
    assert "sensitive detail" not in str(record.pipeline)


def test_stage_timer_mark_failure_reports_budget_exceeded(caplog):
    with caplog.at_level(logging.WARNING, logger="app.creative.pipeline"):
        with StageTimer(stage="create_directions", business_id="b1", provider="higgsfield") as timer:
            timer.mark_failure("budget_exceeded")

    [record] = caplog.records
    assert record.pipeline["result"] == "budget_exceeded"
