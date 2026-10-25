"""The contract every automation follows.

An automation is a class with a `slug` and a `run(ctx, payload)` method.
Inside `run` it wraps each piece of work in `with ctx.step("node_id") as s:`
and the engine does the rest: timing, logging, cost, failures.

    @register
    class LeadHandler(BaseAutomation):
        slug = "lead_handler"
        def run(self, ctx, payload):
            with ctx.step("classify", payload) as s:
                s.output = {...}
"""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from app.engine.context import RunContext


class BaseAutomation:
    slug: ClassVar[str]

    def run(self, ctx: "RunContext", payload: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class NeedsApproval(Exception):
    """Raise inside `run` to pause the run for a human.

    The engine saves an Approval row and sets the run to `waiting_approval`.
    Phase 2 adds the endpoint that resumes it after the human decides.
    """

    def __init__(self, kind: str, reason: str, payload: dict, output: dict | None = None):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason
        self.payload = payload
        self.output = output or {}


IMPLEMENTATIONS: dict[str, BaseAutomation] = {}


def register(cls: type[BaseAutomation]) -> type[BaseAutomation]:
    """Class decorator: makes an automation runnable by its slug."""
    if cls.slug in IMPLEMENTATIONS:
        raise ValueError(f"Automation '{cls.slug}' registered twice")
    IMPLEMENTATIONS[cls.slug] = cls()
    return cls


def get_implementation(slug: str) -> BaseAutomation | None:
    return IMPLEMENTATIONS.get(slug)
