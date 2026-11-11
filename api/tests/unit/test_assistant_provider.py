import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import assistant as ai


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_transient_provider_error_retries_once(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "unit-test-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash-lite")
    monkeypatch.setattr(ai.time, "sleep", lambda _: None)
    responses = [
        FakeResponse(503, {"error": {"status": "UNAVAILABLE"}}),
        FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "A grounded reply."}]}}]}),
    ]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(ai.httpx, "post", fake_post)

    result = ai.ask_gemini([{"role": "user", "text": "hi"}], "system")

    assert result == "A grounded reply."
    assert len(calls) == 2
    assert all("models/gemini-3.5-flash-lite:generateContent" in call[0][0] for call in calls)


def test_configuration_error_is_actionable_and_does_not_retry(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "unit-test-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash-lite")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(True)
        return FakeResponse(403, {"error": {
            "status": "PERMISSION_DENIED",
            "message": "model access denied for unit-test-key",
        }})

    monkeypatch.setattr(ai.httpx, "post", fake_post)

    with pytest.raises(HTTPException) as raised:
        ai.ask_gemini([{"role": "user", "text": "hi"}], "system")
    assert raised.value.status_code == 502
    assert "configuration update" in raised.value.detail

    assert len(calls) == 1
    assert "PERMISSION_DENIED" in caplog.text
    assert "unit-test-key" not in caplog.text
