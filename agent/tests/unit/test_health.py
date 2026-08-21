import httpx
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.shared.config import get_settings
from app.shared.secrets import set_gemini_api_key


def test_health_reports_ok_when_citron_ready_and_gemini_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()

    async def fake_ready() -> bool:
        return True

    monkeypatch.setattr(main_module, "_citron_ready", fake_ready)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["services"] == {"citron": True, "gemini": True}


def test_health_reports_degraded_when_citron_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    # A real .env in this repo sets GEMINI_API_KEY for local dev — an empty process env
    # var overrides it (pydantic-settings prioritizes env vars over the .env file),
    # whereas delenv alone would leave the .env file's value in effect.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    async def fake_ready() -> bool:
        return False

    monkeypatch.setattr(main_module, "_citron_ready", fake_ready)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"] == {"citron": False, "gemini": False}


async def test_citron_ready_returns_false_on_non_200(monkeypatch):
    monkeypatch.setenv("CITRON_URL", "http://citron.test")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        return httpx.Response(503, json={"status": "unavailable"})

    # The probe client is a module-level singleton now (built once, not per request), so
    # the transport is swapped on that instance rather than on httpx.AsyncClient.
    monkeypatch.setattr(
        main_module, "_probe_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    assert await main_module._citron_ready() is False
    get_settings.cache_clear()


async def test_health_reports_gemini_ok_from_a_stored_key(tmp_path, monkeypatch):
    """The Docker path: no GEMINI_API_KEY in the environment, key entered through the UI."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    async def fake_ready() -> bool:
        return True

    monkeypatch.setattr(main_module, "_citron_ready", fake_ready)

    with TestClient(app) as client:
        assert client.get("/health").json()["services"]["gemini"] is False
        await set_gemini_api_key("stored-key")
        assert client.get("/health").json()["services"]["gemini"] is True

    get_settings.cache_clear()
