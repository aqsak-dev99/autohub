"""Database tables.

The hub's core idea: every automation execution is a `Run`, and every step
inside it is a `RunStep`. That one design gives us the dashboard, the React
Flow visualizer, cost tracking and debugging for free, for every automation.

    Automation 1──* Run 1──* RunStep
                     │
                     ├──* Approval   (human-in-the-loop decisions)
                     ├──* Lead       (output of the lead handler)
                     └──* Document   (output of the document extractor)
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- status enums (stored as strings so the DB stays readable) ----------

class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"  # paused for a human
    succeeded = "succeeded"
    failed = "failed"


class StepStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    waiting = "waiting"    # paused on a human decision


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    edited = "edited"      # human changed the AI draft, then approved
    rejected = "rejected"


def _enum(e):
    return Enum(e, native_enum=False, length=32)


# ---------- tables ----------

class Automation(Base):
    """A registered automation, e.g. 'lead_handler'. `graph` is the node/edge
    layout React Flow draws in the dashboard."""
    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(32))  # webhook | upload | schedule
    enabled: Mapped[bool] = mapped_column(default=True)
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list["Run"]] = relationship(back_populates="automation")


class Run(Base):
    """One execution of an automation, with totals rolled up from its steps."""
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[int] = mapped_column(ForeignKey("automations.id"), index=True)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), default=RunStatus.queued, index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    automation: Mapped[Automation] = relationship(back_populates="runs")

    @property
    def label(self) -> str | None:
        """'Ayesha · web_form' for a lead, 'n8n · 24h' for a digest: what the dashboard shows in run lists."""
        data = self.input or {}
        who = data.get("name") or data.get("contact")
        if who:
            return f"{who} · {data['channel']}" if data.get("channel") else str(who)
        if data.get("source") or data.get("hours"):
            return f"{data.get('source', 'manual')} · {data.get('hours', 24)}h"
        return None

    steps: Mapped[list["RunStep"]] = relationship(
        back_populates="run", order_by="RunStep.position", cascade="all, delete-orphan"
    )


class RunStep(Base):
    """One node in a run. `node_id` matches a node in Automation.graph, so the
    dashboard can colour the right node on the React Flow canvas."""
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[StepStatus] = mapped_column(_enum(StepStatus), default=StepStatus.running)

    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)  # >1 means retries happened

    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")


class Approval(Base):
    """Human-in-the-loop queue. Created when the AI isn't confident enough."""
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # reply_draft | extraction
    reason: Mapped[str] = mapped_column(Text)      # why it needs a human
    payload: Mapped[dict] = mapped_column(JSON)    # what the AI proposed
    final_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # what the human sent
    status: Mapped[ApprovalStatus] = mapped_column(
        _enum(ApprovalStatus), default=ApprovalStatus.pending, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Lead(Base):
    """A customer inquiry processed by the lead handler.

    Created the moment a message arrives (so it shows up even while waiting
    for approval), then enriched as the run moves through its steps.
    """
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))   # email | web_form | web_chat
    contact: Mapped[str] = mapped_column(String(128))  # phone or email
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text)

    # from the classify step
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # from the qualify step (LLM extracts the facts, code computes the score)
    services: Mapped[list | None] = mapped_column(JSON, nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    monthly_budget_pkr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_band: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timeline: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[str | None] = mapped_column(String(16), nullable=True)  # hot | warm | cold | not_a_lead
    score_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # reply
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    # new | awaiting_approval | replied | rejected | spam

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Document(Base):
    """An invoice/receipt processed by the document extractor."""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(512))
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_valid: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class InboundMessage(Base):
    """Every message received from a provider, keyed by the provider's own id.

    The same email can be fetched twice (two polls overlap) and a form can be
    submitted twice (double-click). The unique external_id makes the second
    delivery a no-op instead of a second lead and a second reply.
    """
    __tablename__ = "inbound_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))           # email | form
    external_id: Mapped[str] = mapped_column(String(128), unique=True)  # email Message-ID hash / form fingerprint
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """Settings the business owner changes from the dashboard (e.g. the Lead Handler's rules).

    Environment variables stay the defaults; a row here overrides them, so a rule
    change takes effect on the next message without a redeploy.
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
