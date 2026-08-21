"""Every error leaves the API as {"error": "<sentence>"} — the client parses one shape.

Handlers are exercised on a throwaway app rather than app.main: the SPA catch-all route is
registered at import time, so any route added afterwards is unreachable behind it.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import app as real_app
from app.shared.errors import NotFoundError, register_exception_handlers


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/http-error")
    async def _http_error():
        raise HTTPException(status_code=418, detail="I am a teapot")

    @app.get("/domain-error")
    async def _domain_error():
        raise NotFoundError("Widget not found")

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("dependency exploded")

    return TestClient(app, raise_server_exceptions=False)


def test_http_exception_uses_the_error_envelope(client):
    response = client.get("/http-error")
    assert response.status_code == 418
    assert response.json() == {"error": "I am a teapot"}


def test_domain_error_uses_the_error_envelope(client):
    assert client.get("/domain-error").json() == {"error": "Widget not found"}


def test_unhandled_error_is_json_not_plain_text(client):
    """Starlette's default is a plain-text body, which the client's JSON error parsing
    can't read at all — it would show a generic fallback instead of anything useful."""
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"].startswith("Something went wrong")
    assert "dependency exploded" not in response.text


def test_validation_error_names_the_field(tmp_path, monkeypatch):
    from app.shared.config import get_settings

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    with TestClient(real_app) as client:
        response = client.post("/api/problem-sessions/x/chat", json={})
    assert response.status_code == 422
    assert response.json() == {"error": "content: Field required"}
    get_settings.cache_clear()


def test_unmatched_api_path_404s_instead_of_serving_the_spa(tmp_path, monkeypatch):
    """The catch-all used to return index.html with a 200 for any unmatched /api path, so
    a removed or misspelled endpoint looked like success until the JSON parse failed."""
    from app.shared.config import get_settings

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    with TestClient(real_app) as client:
        response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}
    get_settings.cache_clear()
