import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.setup.router as setup_router
from app.main import app
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.secrets import (
    GEMINI_API_KEY,
    gemini_key_status,
    get_gemini_api_key,
    set_gemini_api_key,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated DB + empty env key, so the repo's real .env never bleeds into a test."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    run_migrations()
    yield path
    get_settings.cache_clear()


async def test_stored_key_round_trips_and_is_encrypted_at_rest(db):
    await set_gemini_api_key("AIza-super-secret-1234")

    assert await get_gemini_api_key() == "AIza-super-secret-1234"

    stored = sqlite3.connect(db).execute(
        "SELECT value FROM app_settings WHERE key = ?", (GEMINI_API_KEY,)
    ).fetchone()[0]
    assert "AIza-super-secret-1234" not in stored


async def test_env_key_wins_over_stored_key(db, monkeypatch):
    await set_gemini_api_key("stored-key")
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    get_settings.cache_clear()

    assert await get_gemini_api_key() == "env-key"
    assert (await gemini_key_status())["source"] == "env"


async def test_status_never_exposes_the_key(db):
    await set_gemini_api_key("AIza-super-secret-1234")

    with TestClient(app) as client:
        response = client.get("/api/setup/gemini-key")

    assert response.status_code == 200
    assert "AIza-super-secret-1234" not in response.text
    assert response.json() == {"configured": True, "source": "stored", "masked": "...1234"}


async def test_rejected_key_is_not_stored(db, monkeypatch):
    await set_gemini_api_key("known-good-key")

    async def reject(api_key: str) -> None:
        raise ValueError("Gemini rejected that key.")

    monkeypatch.setattr(setup_router, "validate_gemini_key", reject)

    with TestClient(app) as client:
        response = client.put("/api/setup/gemini-key", json={"api_key": "bogus"})

    assert response.status_code == 400
    assert response.json()["error"] == "Gemini rejected that key."
    # The previously working key must survive a failed attempt.
    assert await get_gemini_api_key() == "known-good-key"


async def test_accepted_key_is_stored(db, monkeypatch):
    async def accept(api_key: str) -> None:
        return None

    monkeypatch.setattr(setup_router, "validate_gemini_key", accept)

    with TestClient(app) as client:
        response = client.put("/api/setup/gemini-key", json={"api_key": "  AIza-new-key  "})

    assert response.status_code == 200
    assert response.json()["configured"] is True
    # Whitespace from a paste is trimmed before both validation and storage.
    assert await get_gemini_api_key() == "AIza-new-key"


async def test_delete_forgets_a_stored_key(db):
    await set_gemini_api_key("AIza-super-secret-1234")

    with TestClient(app) as client:
        response = client.delete("/api/setup/gemini-key")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "source": None, "masked": None}
    assert await get_gemini_api_key() is None


async def test_delete_cannot_remove_an_env_key(db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.delete("/api/setup/gemini-key")

    # The env var still wins — the UI uses `source` to disable Remove in this case.
    assert response.json()["source"] == "env"
    assert await get_gemini_api_key() == "env-key"
