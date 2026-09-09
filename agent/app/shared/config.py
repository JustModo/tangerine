from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
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
