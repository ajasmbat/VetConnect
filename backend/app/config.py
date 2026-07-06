"""Application settings.

All configuration comes from environment variables (or a local `.env` file).
Nothing is hard-coded that shouldn't be — secrets stay out of the repo.

Privacy note: VetConnect only reads *public* VA facility data. It never fetches,
stores, or logs Protected Health Information (PHI).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration in one place.

    Each field can be overridden by setting an env var of the same name
    (e.g. `VA_API_KEY=abc123`) or by adding it to a `.env` file at the
    backend root.

    Fields:
        va_api_key:                  Auth key for the VA Facilities API
                                     (required in prod).
        va_api_base_url:             Which VA environment to hit (sandbox vs
                                     production).
        openai_api_key:              OpenAI key. If empty, the app falls back
                                     to keyword parsing + template answers
                                     (still fully functional).
        openai_model:                Which OpenAI chat model to use.
        sqlite_path:                 Where to keep the local cache/log DB file.
        cors_origin:                 The single frontend origin allowed to call
                                     this API.
        assistant_rate_per_minute:   Per-IP request cap on /api/assistant in a
                                     rolling 60-second window. Guards the LLM
                                     budget from bursty scrapers.
        assistant_rate_per_hour:     Same, over a rolling 3600-second window.
                                     Guards the daily budget.
        openai_api_base_url:         OpenAI-compatible chat/completions
                                     endpoint. Override to use Azure OpenAI,
                                     a LiteLLM proxy, or a self-hosted model.
        nominatim_url:               Geocoder endpoint. Defaults to OSM's
                                     public Nominatim; point at a self-hosted
                                     instance if you have volume.
        nominatim_user_agent:        Distinctive UA sent to Nominatim.
                                     REQUIRED to be changed when you fork or
                                     deploy — OSM blocks generic identifiers.
    """

    va_api_key: str = ""
    va_api_base_url: str = "https://sandbox-api.va.gov/services/va_facilities/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_api_base_url: str = "https://api.openai.com/v1/chat/completions"
    sqlite_path: str = "vetconnect.db"
    cors_origin: str = "http://localhost:5173"
    assistant_rate_per_minute: int = 10
    assistant_rate_per_hour: int = 60
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "VetConnect-Dev/1.0 (+https://github.com/ajasmbat/VetConnect)"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings instance.

    Cached with `lru_cache` so we only parse env vars once. Call this anywhere
    you need config — never instantiate `Settings()` directly.

    Returns:
        Settings: the shared, immutable settings object.
    """
    return Settings()
