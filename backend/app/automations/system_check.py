"""System Check: a 3-step automation that proves the whole engine works.

Run it after setup or a deploy. If it succeeds, the queue, worker, Groq key,
model names, retries, cost tracking and structured output are all working.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.engine.base import BaseAutomation, register
from app.engine.context import RunContext


class SelfTest(BaseModel):
    status: Literal["ok"]
    model_says: str = Field(description="One short sentence about what an automation hub does")


@register
class SystemCheck(BaseAutomation):
    slug = "system_check"

    def run(self, ctx: RunContext, payload: dict) -> dict:
        settings = ctx.llm.settings

        with ctx.step("models") as s:
            # catches a typo'd or retired model name before any automation hits it
            available = {m.id for m in ctx.llm.sdk.models.list().data}
            wanted = {"text": settings.groq_text_model, "vision": settings.groq_vision_model}
            missing = {role: m for role, m in wanted.items() if m not in available}
            s.output = {"configured": wanted, "missing": missing, "available_count": len(available)}
            if missing:
                raise RuntimeError(f"Model(s) not available on your Groq account: {missing}")

        with ctx.step("llm_text") as s:
            result = s.llm([{"role": "user", "content": "Reply with exactly: pong"}], max_tokens=200)
            s.output = {"reply": result.content.strip()}

        with ctx.step("llm_json") as s:
            result = s.llm_json(
                [{"role": "user", "content": "Return status ok and one short sentence "
                                             "about what an automation hub does."}],
                SelfTest,
                max_tokens=300,
            )
            s.output = {"parsed": result.parsed, "repairs": result.repairs}

        return {"ok": True, "message": result.parsed.model_says}
