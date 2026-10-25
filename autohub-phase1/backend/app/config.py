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
    groq_text_model: str = "openai/gpt-oss-20b"
    groq_vision_model: str = "qwen/qwen3.8-27b"

    # run engine
    run_mode: str = "queue"      # queue (Redis worker) | inline (inside the API process)
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3     # attempts per LLM call for transient errors (429, 5xx, timeouts)

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
