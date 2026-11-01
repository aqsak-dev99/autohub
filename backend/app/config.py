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
    llm_max_retries: int = 3         # attempts per LLM call for 5xx errors and timeouts
    llm_rate_limit_retries: int = 6  # attempts when rate limited (429): waits add up to about a minute

    # sending
    send_mode: str = "dry_run"        # dry_run (record only) | live (really send email)

    # Email (Gmail): SMTP sends replies, IMAP reads the inbox
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465              # SSL
    smtp_username: str = ""           # the Gmail address AutoHub uses
    smtp_password: str = ""           # a Google *app password*, never the account password
    email_from_name: str = "flowpath"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_folder: str = "INBOX"
    email_poll_since_days: int = 1    # only read unread mail from the last N days (protects an old backlog)
    email_poll_max: int = 20          # most messages handled per poll
    email_send_allowlist: str = ""    # comma-separated addresses; if set, live emails go ONLY to these

    # daily digest
    digest_email_to: str = ""         # your own email

    # lead handler
    groq_draft_model: str = "openai/gpt-oss-120b"  # the customer-facing reply gets the stronger model
    auto_send_confidence: float = 0.80
    review_languages: str = "urdu,arabic"          # always reviewed until evals prove them reliable
    inbound_api_key: str = ""                      # if set, POST /api/leads/inbound needs header X-AutoHub-Key
    form_allowed_origins: str = ""                 # comma-separated site origins allowed to post the public contact form
    form_rate_limit_per_hour: int = 5              # per email address / IP, so the form can't be used to spam

    frontend_origin: str = "http://localhost:5173"

    @property
    def review_language_set(self) -> set[str]:
        return {x.strip() for x in self.review_languages.split(",") if x.strip()}

    @property
    def email_allowlist(self) -> set[str]:
        return {x.strip().lower() for x in self.email_send_allowlist.split(",") if x.strip()}

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_username and self.smtp_password)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache  # read env once, reuse everywhere
def get_settings() -> Settings:
    return Settings()
