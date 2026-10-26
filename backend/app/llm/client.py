"""Thin wrapper around the Groq SDK that every automation goes through.

It adds three things the raw SDK doesn't give you:
1. Retries with exponential backoff + jitter, but ONLY for transient errors
   (rate limits, 5xx, timeouts). A bad request is a bug, so it fails at once.
   Rate limits get more attempts and honour the provider's Retry-After hint.
2. Usage accounting: tokens, cost and attempts on every call, which the run
   tracer stores per step.
3. `complete_json`: asks for JSON, validates it against a Pydantic schema,
   and if the model gets it wrong, sends the validation errors back once so
   it can fix its own output. Groq's own "invalid JSON" 400 (cut-off output)
   is repaired the same way. Every attempt's tokens are counted.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import RetryCallState, Retrying, retry_if_exception, wait_exponential_jitter

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


def _is_json_generation_error(exc: BaseException) -> bool:
    """Groq's JSON mode rejects output that isn't valid JSON with a 400 (code json_validate_failed),
    usually because the answer was cut off. That's a bad *output*, not a bad request, so it's repairable."""
    if getattr(exc, "status_code", None) != 400:
        return False
    body = getattr(exc, "body", None)
    code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
    return code == "json_validate_failed" or "json_validate_failed" in str(exc) or "validate JSON" in str(exc)


_TRY_AGAIN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", re.IGNORECASE)


def _retry_after(exc: BaseException | None) -> float | None:
    """How long the provider asked us to wait, from the Retry-After header or the error text."""
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("retry-after") if response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _TRY_AGAIN.search(str(exc or ""))
    if match:
        minutes, amount, unit = match.groups()
        seconds = float(amount) / 1000 if unit.lower() == "ms" else float(amount)
        return seconds + 60 * int(minutes or 0)
    return None


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
        reasoning_effort: str = "low",
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
            # reasoning models: low keeps it fast and cheap; careful checking steps ask for more
            kwargs["reasoning_effort"] = reasoning_effort

        attempts = 0
        backoff = wait_exponential_jitter(multiplier=2, max=30)

        def stop(state: RetryCallState) -> bool:
            # rate limits get a bigger budget: on a free plan they clear within a minute
            exc = state.outcome.exception() if state.outcome else None
            limit = (self.settings.llm_rate_limit_retries if getattr(exc, "status_code", None) == 429
                     else self.settings.llm_max_retries)
            return state.attempt_number >= limit

        def wait(state: RetryCallState) -> float:
            # wait at least as long as the provider asked, never less than our own backoff
            exc = state.outcome.exception() if state.outcome else None
            hinted = _retry_after(exc)
            seconds = backoff(state)
            if hinted is not None:
                seconds = max(seconds, hinted + random.uniform(0.2, 1.0))
            return min(seconds, 60.0)

        retrying = Retrying(retry=retry_if_exception(_is_transient), stop=stop, wait=wait, reraise=True)
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
        reasoning_effort: str = "low",
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
        errors: list[str] = []
        for repair in range(max_repairs + 1):
            try:
                result = self.complete(
                    convo, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=True,
                    reasoning_effort=reasoning_effort,
                )
            except Exception as exc:
                if not _is_json_generation_error(exc):
                    raise
                # the provider rejected cut-off or broken JSON: ask again for a complete, shorter answer
                errors.append("provider rejected the output as invalid JSON (probably cut off)")
                if total is not None:
                    total.attempts += 1
                convo = convo + [{"role": "user", "content": "Your last answer was not valid JSON, probably because "
                                  "it was cut off. Return the complete JSON object only, and keep it short."}]
                continue
            if total is None:
                total = result
            else:
                total.absorb(result)
                total.content = result.content
            try:
                total.parsed = schema.model_validate_json(result.content)
                total.repairs = repair
                total.raw_errors = errors + total.raw_errors
                return total
            except ValidationError as exc:
                error_text = _short_errors(exc)
                errors.append(error_text)
                # feed the mistake back so the model can correct itself
                convo = convo + [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": f"That JSON was invalid: {error_text}. "
                                                "Return the corrected JSON object only."},
                ]
        raise LLMOutputError(f"Invalid JSON after {max_repairs} repair(s): {errors[-1]}")


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
