from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# shared -> app -> agent -> repo root. Absolute so it resolves no matter what the CWD is
# (`scripts/run.js` runs uvicorn from agent/, but tests and ad-hoc scripts don't).
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Fixed deployment config. The .env file is a DEV CONVENIENCE ONLY — under Docker
    these come from compose, and the Gemini key comes from the database (see
    app/shared/secrets.py), supplied by the user through the web UI."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    database_path: str = "agent.db"
    llm_model: str = "gemini-flash-lite-latest"
    gemini_api_key: str | None = None
    citron_url: str = "http://localhost:2358"
    citron_auth_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
