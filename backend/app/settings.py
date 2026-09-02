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

    llm_timeout_seconds: float = 10.0
    llm_max_retries: int = 2

    # Images -----------------------------------------------------------------
    pollinations_base_url: str = "https://image.pollinations.ai/prompt"

    # Delivery ---------------------------------------------------------------
    delivery_adapter: str = "console"          # console | twilio_wa
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    # Scheduler --------------------------------------------------------------
    scheduler_enabled: bool = False
    scheduler_hour: int = 2
    scheduler_minute: int = 0

    # Frontend ---------------------------------------------------------------
    api_base_url: str = "http://127.0.0.1:8000"

    timezone: str = "Asia/Kolkata"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
