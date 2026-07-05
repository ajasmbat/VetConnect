from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # VetConnect only ever reads public VA facility data. No PHI is fetched,
    # stored, or logged. All secrets live in environment variables.
    va_api_key: str = ""
    va_api_base_url: str = "https://sandbox-api.va.gov/services/va_facilities/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    sqlite_path: str = "vetconnect.db"
    cors_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
