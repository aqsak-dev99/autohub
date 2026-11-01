"""Lead intake, the approval inbox and knowledge-base search.

POST /api/leads/inbound is the server-to-server intake (n8n, scripts, other systems),
protected by X-AutoHub-Key. The public website form uses /api/forms/contact instead. It answers 202 at once; the Lead Handler runs in the worker.
"""
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_role
from app.automations.lead_handler import LeadIn, edit_similarity
from app.config import get_settings
from app.ratelimit import client_ip
from app.db import get_db
from app.engine.dispatch import dispatch, dispatch_resume
from app.engine.executor import claim, create_run
from app.knowledge import get_kb
from app.models import Approval, ApprovalStatus, InboundMessage, Lead, Run
from app.schemas import ApprovalOut, LeadOut

router = APIRouter(prefix="/api", tags=["leads"])


def require_inbound_key(x_autohub_key: str | None = Header(default=None)) -> None:
    expected = get_settings().inbound_api_key
    # constant-time compare, so the key can't be guessed one character at a time
    if expected and not (x_autohub_key and secrets.compare_digest(x_autohub_key, expected)):
        raise HTTPException(401, "Missing or wrong X-AutoHub-Key header")


class InboundOut(BaseModel):
    run_id: str
    status: str
    dispatched_via: str


@router.post("/leads/inbound", response_model=InboundOut, status_code=202,
             dependencies=[Depends(require_inbound_key)])
def inbound_lead(body: LeadIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    run = create_run(db, "lead_handler", body.model_dump())
    via = dispatch(run.id, background)
    return InboundOut(run_id=str(run.id), status=run.status.value, dispatched_via=via)


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    temperature: str | None = Query(None, description="hot | warm | cold | not_a_lead"),
    status: str | None = Query(None, description="new | awaiting_approval | replied | rejected | spam"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    if temperature:
        stmt = stmt.where(Lead.temperature == temperature)
    if status:
        stmt = stmt.where(Lead.status == status)
    return db.scalars(stmt).all()


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: str = "pending", limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    stmt = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(Approval.status == status)
    return db.scalars(stmt).all()


class DecisionIn(BaseModel):
    action: str  # approve | edit | reject
    reply: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def check(self):
        if self.action not in {"approve", "edit", "reject"}:
            raise ValueError("action must be approve, edit or reject")
        if self.action == "edit" and not (self.reply and self.reply.strip()):
            raise ValueError("an edit needs the new reply text")
        return self


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
def decide(approval_id: int, body: DecisionIn, background: BackgroundTasks, db: Session = Depends(get_db),
           role: str = Depends(current_role)):
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    if role == "viewer" and approval.payload.get("contact") != TEST_CONTACT:
        # demo visitors can finish the loop on their own test message, not on anyone else's
        raise HTTPException(403, "Demo visitors can approve replies to their own test messages. Try it on Home!")
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(409, f"Already decided: {approval.status.value}")

    draft = approval.payload.get("reply", "")
    if body.action == "reject":
        status, final_payload = ApprovalStatus.rejected, {"note": body.note}
    else:
        final = body.reply.strip() if body.action == "edit" else draft
        changed = body.action == "edit" and final != draft.strip()
        status = ApprovalStatus.edited if changed else ApprovalStatus.approved
        final_payload = {"reply": final, "similarity": edit_similarity(draft, final), "note": body.note}
    # one conditional UPDATE: two clicks (or two tabs) arriving together can't both decide,
    # so the reply can't be sent twice. The check above only gives a nicer message.
    if not claim(db, Approval, approval_id, ApprovalStatus.pending, status=status,
                 final_payload=final_payload, decided_at=datetime.now(timezone.utc)):
        db.refresh(approval)
        raise HTTPException(409, f"Already decided: {approval.status.value}")
    db.refresh(approval)

    dispatch_resume(approval.run_id, approval.id, background)
    return approval


@router.get("/knowledge/search")
def search_knowledge(q: str = Query(..., min_length=1), limit: int = Query(3, le=10)):
    """Debug view of what the Lead Handler would retrieve for a query."""
    kb = get_kb()
    return {
        "kb_version": kb.version,
        "hits": [{"id": p.id, "label": p.label, "url": p.url, "score": s, "text": p.text}
                 for p, s in kb.search(q, limit=limit)],
    }


class FollowUpOut(BaseModel):
    run_id: uuid.UUID
    status: str                        # the run's: queued | running | waiting_approval | succeeded | failed
    reply: str | None                  # sent, or the draft waiting for the owner
    delivery_mode: str | None = None   # live | dry_run, once sent
    approval: ApprovalOut | None
    created_at: datetime


class ConversationOut(BaseModel):
    lead: LeadOut | None
    approval: ApprovalOut | None
    follow_up: FollowUpOut | None = None


@router.get("/conversations/{run_id}", response_model=ConversationOut)
def conversation(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """The lead and (if any) the approval behind one Lead Handler run: the X-ray page's extra data."""
    lead = db.scalar(select(Lead).where(Lead.run_id == run_id))
    approval = db.scalar(select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at.desc()))
    follow_up = None
    if lead is not None:
        # the Follow-up Nudge run for this lead, if one was started (claimed as follow_up:<lead id>)
        claim_row = db.scalar(select(InboundMessage).where(InboundMessage.external_id == f"follow_up:{lead.id}"))
        fu_run = db.get(Run, claim_row.run_id) if claim_row and claim_row.run_id else None
        if fu_run is not None:
            fu_approval = db.scalar(select(Approval).where(Approval.run_id == fu_run.id))
            draft = next((s.output or {} for s in fu_run.steps if s.node_id == "draft"), {}).get("reply")
            sent = next((s.output or {} for s in fu_run.steps if s.node_id == "send"), {})
            follow_up = FollowUpOut(run_id=fu_run.id, status=fu_run.status.value, approval=fu_approval,
                                    delivery_mode=sent.get("mode"),
                                    reply=lead.follow_up_reply or (fu_approval.payload.get("reply") if fu_approval else draft),
                                    created_at=fu_run.created_at)
    return ConversationOut(lead=lead, approval=approval, follow_up=follow_up)


class TestMessageIn(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    name: str = Field(default="Test customer", max_length=60)


TEST_CONTACT = "dashboard-test"
_try_hits: dict[str, deque] = defaultdict(deque)  # per visitor, in memory


def _check_try_it_limits(request: Request, db: Session) -> None:
    """Every test message costs real AI calls, so a public demo needs a ceiling."""
    settings = get_settings()
    ip = client_ip(request)
    now, hits = time.monotonic(), _try_hits[ip]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= settings.try_it_per_hour:
        raise HTTPException(429, f"That's {settings.try_it_per_hour} test messages this hour. Please try again a bit later.")
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if db.bind.dialect.name == "sqlite":
        midnight = midnight.replace(tzinfo=None)
    today = db.scalar(select(func.count()).select_from(Run).where(
        Run.created_at >= midnight, Run.input["contact"].as_string() == TEST_CONTACT))
    if today >= settings.try_it_per_day:
        raise HTTPException(429, "The demo has reached today's limit of test messages. Please come back tomorrow.")
    hits.append(now)


@router.post("/test-message", response_model=InboundOut, status_code=202)
def test_message(body: TestMessageIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """'Try it' on the dashboard: play a customer. Sent as website chat, so the reply is shown
    on screen and never emailed. Open to demo visitors, within the limits above."""
    _check_try_it_limits(request, db)
    run = create_run(db, "lead_handler", {"channel": "web_chat", "contact": TEST_CONTACT, "name": body.name,
                                          "message": body.message})
    via = dispatch(run.id, background)
    return InboundOut(run_id=str(run.id), status=run.status.value, dispatched_via=via)
