"""Application settings, read from environment / .env once at import time."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "LocalAI OS"
    debug: bool = True

    # Database ---------------------------------------------------------------
    database_url: str = "sqlite:///./localai.db"

    # LLM --------------------------------------------------------------------
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1/chat/completions"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/models"

    # Providers are tried in this order. Gemini first: generous free tier.
    llm_provider_order: str = "gemini,groq"
    llm_timeout_seconds: float = 10.0
    llm_max_retries: int = 2
    llm_rate_limit_per_minute: int = 12
    llm_cache_hours: int = 24
    llm_batch_size: int = 20

    @property
    def provider_order(self) -> list[str]:
        return [
            name.strip().lower()
            for name in (self.llm_provider_order or "").split(",")
            if name.strip()
        ] or ["gemini", "groq"]

    # Images -----------------------------------------------------------------
    pollinations_base_url: str = "https://image.pollinations.ai/prompt"

    # Delivery ---------------------------------------------------------------
    delivery_adapter: str = "console"          # console | twilio_wa
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    # Meta WhatsApp Cloud API
    whatsapp_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_api_version: str = "v21.0"

    # Guard rails. A bug must not be able to spam a real person.
    delivery_daily_cap: int = 50
    delivery_rate_limit_per_minute: int = 10

    # Auth ---------------------------------------------------------------------
    # Enforced in the API, not only hidden in the UI. Turn it off only for local
    # experiments; the deployed instance must run with it on.
    auth_enabled: bool = True
    # No fallback on purpose: a guessable default here would defeat auth entirely.
    # Set JWT_SECRET in the environment (python -c "import secrets; print(secrets.token_urlsafe(48))").
    jwt_secret: str
    jwt_expiry_minutes: int = 720
    jwt_cookie_name: str = "localai_token"

    # Scheduler --------------------------------------------------------------
    scheduler_enabled: bool = False
    scheduler_hour: int = 2
    scheduler_minute: int = 0

    # Frontend ---------------------------------------------------------------
    api_base_url: str = "http://127.0.0.1:8000"

    timezone: str = "Asia/Kolkata"

    # Observability
    json_logs: bool = False
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
