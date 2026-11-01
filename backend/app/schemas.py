"""API response shapes. Separate from DB models so the API contract
doesn't change every time a table gets a new column."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AutomationOut(ORM):
    id: int
    slug: str
    name: str
    description: str
    trigger: str
    enabled: bool


class AutomationDetail(AutomationOut):
    graph: dict


class RunStepOut(ORM):
    node_id: str
    position: int
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    attempts: int
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    duration_ms: int
    started_at: datetime
    finished_at: datetime | None


class RunOut(ORM):
    id: uuid.UUID
    automation_id: int
    label: str | None = None  # human-readable: who or what the run was about
    status: str
    total_tokens: int
    total_cost_usd: float
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class RunDetail(RunOut):
    input: dict
    output: dict | None
    steps: list[RunStepOut]


class HealthOut(BaseModel):
    status: str
    database: str
    redis: str
    env: str


class LeadOut(ORM):
    id: int
    run_id: uuid.UUID | None
    channel: str
    contact: str
    name: str | None
    message: str
    language: str | None
    intent: str | None
    services: list | None
    business_type: str | None
    monthly_budget_pkr: int | None
    budget_band: str | None
    timeline: str | None
    score: int | None
    temperature: str | None
    score_reasons: list | None
    confidence: float | None
    reply: str | None
    replied: bool
    replied_at: datetime | None = None
    followed_up_at: datetime | None = None
    follow_up_reply: str | None = None
    status: str
    created_at: datetime


class ApprovalOut(ORM):
    id: int
    run_id: uuid.UUID
    kind: str
    reason: str
    payload: dict
    final_payload: dict | None
    status: str
    created_at: datetime
    decided_at: datetime | None
