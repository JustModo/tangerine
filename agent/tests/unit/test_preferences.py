import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.preferences import PREFERENCES, get_preferences, set_preference


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    get_settings.cache_clear()
    run_migrations()
    yield path
    get_settings.cache_clear()


async def test_unset_preference_resolves_to_its_registry_default(db):
    prefs = await get_preferences()
    assert prefs["default_language"] == PREFERENCES["default_language"]["default"]


async def test_set_preference_round_trips(db):
    await set_preference("default_language", "python")
    assert (await get_preferences())["default_language"] == "python"


async def test_set_preference_rejects_unknown_key(db):
    with pytest.raises(ValueError):
        await set_preference("not_a_real_preference", "whatever")


async def test_set_preference_rejects_value_outside_options(db):
    with pytest.raises(ValueError):
        await set_preference("default_language", "rust")


async def test_get_settings_endpoint_returns_options_and_current_value(db):
    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["default_language"]["value"] == "ask"
    assert set(body["default_language"]["options"]) == set(PREFERENCES["default_language"]["options"])


async def test_patch_settings_endpoint_updates_and_returns_full_shape(db):
    with TestClient(app) as client:
        response = client.patch("/api/settings", json={"default_language": "java"})

    assert response.status_code == 200
    assert response.json()["default_language"]["value"] == "java"
    assert await get_preferences() == {"default_language": "java"}


async def test_patch_settings_endpoint_rejects_unknown_key(db):
    with TestClient(app) as client:
        response = client.patch("/api/settings", json={"bogus_key": "x"})

    assert response.status_code == 400
