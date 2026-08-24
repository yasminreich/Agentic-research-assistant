"""Tests for the HTTP surface (`app/server.py`).

`workflow.run_research` is monkeypatched throughout, so nothing here spends an
API call or touches the network. These tests cover the guardrails that stand
between a public URL and the owner's Anthropic bill.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import server
from app.limits import DailyRunLimiter
from app.workflow import ConfigurationError

RESULT = {
    "question": "Does fasting help?",
    "summary": "It depends.",
    "paper_count": 2,
    "papers": [{"title": "A"}, {"title": "B"}],
    "json_path": "output/x.json",
    "markdown_path": "output/x.md",
    "saved": True,
}


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def stub_run(monkeypatch):
    """Replace the expensive agent run and record what it was called with."""
    calls: list[tuple[tuple, dict]] = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(RESULT)

    monkeypatch.setattr(server, "run_research", _fake)
    return calls


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    """The limiter is module-level state; give each test its own."""
    monkeypatch.setattr(server, "_run_limiter", DailyRunLimiter(max_per_day=50))


class TestHealth:
    def test_reports_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestIndex:
    def test_serves_the_web_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "<html" in response.text.lower()


class TestConfig:
    def test_no_password_configured(self, client, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password=""))
        assert client.get("/config").json()["password_required"] is False

    def test_password_configured(self, client, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        assert client.get("/config").json()["password_required"] is True


class TestResearchAccessGate:
    def test_runs_when_no_password_is_configured(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password=""))
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 200
        assert response.json()["summary"] == "It depends."
        assert len(stub_run) == 1

    def test_rejects_a_wrong_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post(
            "/research",
            json={"question": "Does fasting help?"},
            headers={"X-Access-Password": "wrong"},
        )
        assert response.status_code == 401
        assert stub_run == [], "the run must not start before the gate passes"

    def test_rejects_a_missing_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 401
        assert stub_run == []

    def test_accepts_the_right_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post(
            "/research",
            json={"question": "Does fasting help?"},
            headers={"X-Access-Password": "hunter2"},
        )
        assert response.status_code == 200
        assert len(stub_run) == 1


class TestResearchValidation:
    def test_rejects_a_too_short_question(self, client, stub_run):
        assert client.post("/research", json={"question": "hi"}).status_code == 422
        assert stub_run == []

    def test_rejects_an_over_long_question(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(max_question_chars=20))
        response = client.post("/research", json={"question": "x" * 21})
        assert response.status_code == 422
        assert "too long" in response.json()["detail"]
        assert stub_run == []

    def test_the_question_is_stripped_before_the_run(self, client, stub_run):
        client.post("/research", json={"question": "   Does fasting help?   "})
        assert stub_run[0][0][0] == "Does fasting help?"


class TestDailyRunLimit:
    def test_refuses_once_the_cap_is_reached(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "_run_limiter", DailyRunLimiter(max_per_day=1))
        first = client.post("/research", json={"question": "Does fasting help?"})
        second = client.post("/research", json={"question": "Does fasting help?"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert len(stub_run) == 1

    def test_a_failed_run_gives_its_slot_back(self, client, monkeypatch):
        """A crash must not burn a slot -- nothing was billed."""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        limiter = DailyRunLimiter(max_per_day=1)
        monkeypatch.setattr(server, "_run_limiter", limiter)
        monkeypatch.setattr(server, "run_research", _boom)
        assert client.post("/research", json={"question": "Does fasting help?"}).status_code == 500
        assert limiter.remaining == 1


class TestErrorMapping:
    def test_missing_api_key_is_a_503(self, client, monkeypatch):
        def _raise(*a, **k):
            raise ConfigurationError("ANTHROPIC_API_KEY is not set.")

        monkeypatch.setattr(server, "run_research", _raise)
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 503
        assert "ANTHROPIC_API_KEY" in response.json()["detail"]

    def test_a_bad_value_is_a_422(self, client, monkeypatch):
        def _raise(*a, **k):
            raise ValueError("question must not be empty")

        monkeypatch.setattr(server, "run_research", _raise)
        assert client.post("/research", json={"question": "Does fasting?"}).status_code == 422

    def test_an_unexpected_failure_is_a_500(self, client, monkeypatch):
        def _raise(*a, **k):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(server, "run_research", _raise)
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 500
        assert "upstream exploded" in response.json()["detail"]


class TestResponseShape:
    def test_returns_every_documented_field(self, client, stub_run):
        body = client.post("/research", json={"question": "Does fasting help?"}).json()
        assert set(body) == {
            "question",
            "summary",
            "paper_count",
            "saved",
            "papers",
            "json_path",
            "markdown_path",
        }

    def test_an_empty_run_is_reported_honestly(self, client, monkeypatch):
        empty = dict(RESULT, summary="", paper_count=0, papers=[], saved=False, json_path=None)
        monkeypatch.setattr(server, "run_research", lambda *a, **k: empty)
        body = client.post("/research", json={"question": "Does fasting help?"}).json()
        assert body["saved"] is False
        assert body["paper_count"] == 0


def _settings(**overrides):
    """A Settings instance with test-friendly defaults."""
    from app.config import Settings

    base = {
        "anthropic_api_key": "test-key",
        "access_password": "",
        "max_question_chars": 500,
        "max_runs_per_day": 50,
    }
    return Settings(**{**base, **overrides})
