import dataclasses
import time

from app import config
from app.modelhost import ModelHost


def test_helper_starts_on_demand_and_exits_when_idle(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, model_idle_minutes=0.02))
    host = ModelHost()
    assert not host.running
    assert host.call("ping") == "pong"
    assert host.running
    deadline = time.monotonic() + 15
    while host.running and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not host.running  # gone, and its memory with it
    assert host.call("ping") == "pong"  # and back on the next request
    host.stop()


def test_helper_reports_errors_and_keeps_serving():
    host = ModelHost()
    try:
        host.call("nonsense")
    except RuntimeError as exc:
        assert "unknown op" in str(exc)
    else:
        raise AssertionError("expected an error")
    assert host.call("ping") == "pong"
    host.stop()
