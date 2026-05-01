"""Focused tests for main-thread UI dispatch in DotaBuildApp."""

import queue

from main import DotaBuildApp


def _stub_app():
    app = object.__new__(DotaBuildApp)
    app._ui_queue = queue.Queue()
    scheduled = []
    app.after = lambda delay_ms, callback: scheduled.append((delay_ms, callback))
    app.winfo_exists = lambda: True
    return app, scheduled


def test_drain_ui_queue_runs_pending_callbacks():
    app, scheduled = _stub_app()
    calls = []

    app._enqueue_ui_call(lambda: calls.append("ran"))
    app._drain_ui_queue()

    assert calls == ["ran"]
    assert scheduled
    assert scheduled[0][0] == 50


def test_drain_ui_queue_continues_after_callback_error():
    app, scheduled = _stub_app()
    calls = []

    def boom():
        raise RuntimeError("ui failure")

    app._enqueue_ui_call(boom)
    app._enqueue_ui_call(lambda: calls.append("after-error"))
    app._drain_ui_queue()

    assert calls == ["after-error"]
    assert scheduled


def test_report_tk_callback_exception_emits_error(capsys):
    try:
        raise RuntimeError("tk boom")
    except RuntimeError as exc:
        DotaBuildApp._report_tk_callback_exception(type(exc), exc, exc.__traceback__)

    captured = capsys.readouterr()
    assert "[UI] Tk callback error: tk boom" in captured.out
    assert "RuntimeError: tk boom" in captured.err


def test_should_use_ai_items_rejects_draft_phase():
    use_ai, reason = DotaBuildApp._should_use_ai_items(
        {"confidence": 0.9}, "pre_game", False, [], None
    )

    assert use_ai is False
    assert reason == "draft-phase item AI disabled"


def test_should_use_ai_items_rejects_when_role_engine_is_active():
    use_ai, reason = DotaBuildApp._should_use_ai_items(
        {"confidence": 0.95}, "in_game", True, ["arcane_boots"], "pos4"
    )

    assert use_ai is False
    assert reason == "role-aware rule engine active"
