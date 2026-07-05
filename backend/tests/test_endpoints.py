"""End-to-end tests for the VetConnect API. VA API calls are mocked so tests
never touch the network."""

import httpx
import pytest

from tests.conftest import SAMPLE_FACILITY


class _MockAsyncClient:
    """Drop-in httpx.AsyncClient for tests. Ignores the URL and returns a
    canned payload prepared by the caller."""

    def __init__(self, *_, **__):
        pass

    _payload: dict = {"data": [SAMPLE_FACILITY]}
    _status: int = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, params=None, headers=None):
        return httpx.Response(self._status, json=self._payload, request=httpx.Request("GET", url))

    async def post(self, url, headers=None, json=None):
        # Assistant tests never set OPENAI_API_KEY, so LLM calls fall back.
        return httpx.Response(500, text="unused", request=httpx.Request("POST", url))


@pytest.fixture
def mock_va(monkeypatch):
    monkeypatch.setattr("app.va_client.httpx.AsyncClient", _MockAsyncClient)
    monkeypatch.setattr("app.assistant.httpx.AsyncClient", _MockAsyncClient)
    _MockAsyncClient._payload = {"data": [SAMPLE_FACILITY]}
    _MockAsyncClient._status = 200
    return _MockAsyncClient


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_search_returns_simplified_facilities(client, mock_va):
    r = client.get("/api/facilities/search", params={"lat": 34.05, "long": -118.24})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    f = body["facilities"][0]
    assert f["id"] == "vha_691"
    assert f["name"].startswith("West Los Angeles")
    assert f["address"]["city"] == "Los Angeles"
    assert f["phone"] == "310-478-3711"
    assert "MentalHealthCare" in f["services"]


def test_search_validates_lat_long(client):
    r = client.get("/api/facilities/search", params={"lat": 999, "long": 0})
    assert r.status_code == 422


def test_search_bubbles_upstream_error(client, mock_va):
    mock_va._status = 500
    mock_va._payload = {"errors": [{"detail": "upstream boom"}]}
    r = client.get("/api/facilities/search", params={"lat": 34.05, "long": -118.24})
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]


def test_assistant_keyword_path_finds_service_and_city(client, mock_va):
    r = client.post(
        "/api/assistant",
        json={"question": "mental health near Los Angeles"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_service"] == "MentalHealthCare"
    assert body["parsed_location"] and "los angeles" in body["parsed_location"].lower()
    assert len(body["facilities"]) == 1
    assert body["answer"]  # non-empty template answer


def test_assistant_uses_explicit_coords_when_provided(client, mock_va):
    r = client.post(
        "/api/assistant",
        json={"question": "dental services please", "lat": 33.4484, "long": -112.0740},
    )
    assert r.status_code == 200
    assert r.json()["parsed_service"] == "DentalServices"


def test_assistant_gracefully_reports_no_location(client, mock_va):
    r = client.post("/api/assistant", json={"question": "primary care"})
    assert r.status_code == 200
    body = r.json()
    assert body["facilities"] == []
    assert "city" in body["answer"].lower()


def test_assistant_rejects_empty_question(client):
    r = client.post("/api/assistant", json={"question": ""})
    assert r.status_code == 422
