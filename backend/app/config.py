"""All settings come from environment variables (or .env), validated by Pydantic.

Why: one place to see every knob the app has, and the app fails fast at
startup if a value has the wrong type instead of breaking mid-request.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://autohub:autohub@localhost:5432/autohub"
    redis_url: str = "redis://localhost:6379/0"

    groq_api_key: str = ""
    groq_text_model: str = "llama-3.3-70b-versatile"
    groq_vision_model: str = "qwen/qwen3.6-27b"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    auto_send_confidence: float = 0.80
    frontend_origin: str = "http://localhost:5173"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache  # read env once, reuse everywhere
def get_settings() -> Settings:
    return Settings()
