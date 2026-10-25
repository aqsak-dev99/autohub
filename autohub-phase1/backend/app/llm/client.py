"""Thin wrapper around the Groq SDK that every automation goes through.

It adds three things the raw SDK doesn't give you:
1. Retries with exponential backoff + jitter, but ONLY for transient errors
   (rate limits, 5xx, timeouts). A bad request is a bug, so it fails at once.
2. Usage accounting: tokens, cost and attempts on every call, which the run
   tracer stores per step.
3. `complete_json`: asks for JSON, validates it against a Pydantic schema,
   and if the model gets it wrong, sends the validation errors back once so
   it can fix its own output. Every attempt's tokens are counted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import Settings, get_settings
from app.llm.pricing import cost_usd

T = TypeVar("T", bound=BaseModel)

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Base class for LLM failures the run engine records on a step."""


class LLMNotConfigured(LLMError):
    pass


class LLMOutputError(LLMError):
    """The model kept returning output that doesn't match the schema."""


def _is_transient(exc: BaseException) -> bool:
    # Groq SDK errors carry status_code; connection/timeout errors are transient by nature
    name = type(exc).__name__
    if name in {"APIConnectionError", "APITimeoutError"}:
        return True
    return getattr(exc, "status_code", None) in TRANSIENT_STATUS


@dataclass
class LLMResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    priced: bool = True
    attempts: int = 1
    parsed: Any = None
    repairs: int = 0  # how many times complete_json had to ask the model to fix its JSON
    raw_errors: list[str] = field(default_factory=list)

    def absorb(self, other: "LLMResult") -> None:
        """Add another call's usage to this one (used when repairs need extra calls)."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cost_usd = round(self.cost_usd + other.cost_usd, 8)
        self.attempts += other.attempts
        self.priced = self.priced and other.priced


class LLMClient:
    def __init__(self, settings: Settings | None = None, sdk: Any = None):
        self.settings = settings or get_settings()
        self._sdk = sdk  # tests inject a fake; real SDK is created lazily

    @property
    def sdk(self):
        if self._sdk is None:
            if not self.settings.groq_api_key:
                raise LLMNotConfigured("GROQ_API_KEY is not set. Add it to .env and restart.")
            from groq import Groq

            # max_retries=0: tenacity owns retries, so attempts are counted in one place
            self._sdk = Groq(
                api_key=self.settings.groq_api_key,
                timeout=self.settings.llm_timeout_s,
                max_retries=0,
            )
        return self._sdk

    # ---------- plain completion ----------

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResult:
        model = model or self.settings.groq_text_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            kwargs["reasoning_effort"] = "low"  # reasoning models: keep it fast and cheap

        attempts = 0
        retrying = Retrying(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(self.settings.llm_max_retries),
            wait=wait_exponential_jitter(initial=1, max=20),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                attempts += 1
                response = self.sdk.chat.completions.create(**kwargs)

        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost, priced = cost_usd(model, prompt_tokens, completion_tokens)
        return LLMResult(
            content=response.choices[0].message.content or "",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            priced=priced,
            attempts=attempts,
        )

    # ---------- structured output ----------

    def complete_json(
        self,
        messages: list[dict],
        schema: type[T],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        max_repairs: int = 1,
    ) -> LLMResult:
        """Return an LLMResult whose `.parsed` is a validated `schema` instance."""
        schema_json = json.dumps(schema.model_json_schema())
        convo = [
            {
                "role": "system",
                "content": "Respond with a single JSON object only, no prose, matching this JSON schema:\n"
                + schema_json,
            },
            *messages,
        ]

        total: LLMResult | None = None
        for repair in range(max_repairs + 1):
            result = self.complete(
                convo, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=True
            )
            if total is None:
                total = result
            else:
                total.absorb(result)
                total.content = result.content
            try:
                total.parsed = schema.model_validate_json(result.content)
                total.repairs = repair
                return total
            except ValidationError as exc:
                error_text = _short_errors(exc)
                total.raw_errors.append(error_text)
                # feed the mistake back so the model can correct itself
                convo = convo + [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": f"That JSON was invalid: {error_text}. "
                                                "Return the corrected JSON object only."},
                ]
        raise LLMOutputError(f"Invalid JSON after {max_repairs} repair(s): {total.raw_errors[-1]}")


def _short_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


_default: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
