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

    # WhatsApp: which provider sends and receives
    whatsapp_provider: str = "meta"   # meta (WhatsApp Cloud API) | twilio

    # Meta WhatsApp Cloud API
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
    meta_app_secret: str = ""         # signs webhooks (X-Hub-Signature-256)
    meta_verify_token: str = ""       # any secret string you choose; Meta echoes it when you add the webhook
    meta_graph_version: str = "v23.0"
    meta_validate_signature: bool = True

    # Twilio (alternative provider)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"   # the sandbox number
    send_mode: str = "dry_run"        # dry_run (record only) | live (really send through Twilio)
    live_send_allowlist: str = ""     # comma-separated numbers; if set, live sends go ONLY to these
    public_base_url: str = ""         # e.g. https://<codespace>-8000.app.github.dev, for Twilio signatures
    twilio_validate_signature: bool = True

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
    digest_whatsapp_to: str = ""      # your own number, e.g. +923001234567
    digest_email_to: str = ""         # your own email

    # lead handler
    groq_draft_model: str = "openai/gpt-oss-120b"  # the customer-facing reply gets the stronger model
    auto_send_confidence: float = 0.80
    review_languages: str = "urdu,arabic"          # always reviewed until evals prove them reliable
    inbound_api_key: str = ""                      # if set, POST /api/leads/inbound needs header X-AutoHub-Key

    frontend_origin: str = "http://localhost:5173"

    @property
    def review_language_set(self) -> set[str]:
        return {x.strip() for x in self.review_languages.split(",") if x.strip()}

    @property
    def allowlist(self) -> set[str]:
        return {normalize_phone(x) for x in self.live_send_allowlist.split(",") if x.strip()}

    @property
    def email_allowlist(self) -> set[str]:
        return {x.strip().lower() for x in self.email_send_allowlist.split(",") if x.strip()}

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_username and self.smtp_password)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_access_token and self.meta_phone_number_id)

    @property
    def whatsapp_configured(self) -> bool:
        return self.meta_configured if self.whatsapp_provider == "meta" else self.twilio_configured

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


def normalize_phone(raw: str) -> str:
    """'whatsapp:+92 300-1234567' -> '+923001234567'"""
    raw = raw.strip().removeprefix("whatsapp:")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"+{digits}" if digits else ""


@lru_cache  # read env once, reuse everywhere
def get_settings() -> Settings:
    return Settings()
