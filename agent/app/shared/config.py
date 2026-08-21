from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_path: str = "agent.db"
    llm_provider: str = "gemini"
    llm_model: str = "gemini-flash-lite-latest"
    gemini_api_key: str | None = None
    citron_url: str = "http://localhost:2358"
    citron_auth_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
