"""Lead intake, the approval inbox and knowledge-base search.

POST /api/leads/inbound is the server-to-server intake (n8n, scripts, other systems),
protected by X-AutoHub-Key. The public website form uses /api/forms/contact instead. It answers 202 at once; the Lead Handler runs in the worker.
"""
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automations.lead_handler import LeadIn, edit_similarity
from app.config import get_settings
from app.db import get_db
from app.engine.dispatch import dispatch, dispatch_resume
from app.engine.executor import create_run
from app.knowledge import get_kb
from app.models import Approval, ApprovalStatus, Lead
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
def decide(approval_id: int, body: DecisionIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    if approval.status != ApprovalStatus.pending:
        # stops a double-click from sending the reply twice
        raise HTTPException(409, f"Already decided: {approval.status.value}")

    draft = approval.payload.get("reply", "")
    if body.action == "reject":
        approval.status = ApprovalStatus.rejected
        approval.final_payload = {"note": body.note}
    else:
        final = body.reply.strip() if body.action == "edit" else draft
        changed = body.action == "edit" and final != draft.strip()
        approval.status = ApprovalStatus.edited if changed else ApprovalStatus.approved
        approval.final_payload = {"reply": final, "similarity": edit_similarity(draft, final), "note": body.note}
    approval.decided_at = datetime.now(timezone.utc)
    db.commit()

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


class ConversationOut(BaseModel):
    lead: LeadOut | None
    approval: ApprovalOut | None


@router.get("/conversations/{run_id}", response_model=ConversationOut)
def conversation(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """The lead and (if any) the approval behind one Lead Handler run: the X-ray page's extra data."""
    lead = db.scalar(select(Lead).where(Lead.run_id == run_id))
    approval = db.scalar(select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at.desc()))
    return ConversationOut(lead=lead, approval=approval)


class TestMessageIn(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    name: str = Field(default="Test customer", max_length=60)


@router.post("/test-message", response_model=InboundOut, status_code=202)
def test_message(body: TestMessageIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    """'Try it' on the dashboard: the owner plays a customer. Sent as website chat, so the reply
    is shown on screen and never emailed. (Same protection as the rest of the dashboard.)"""
    run = create_run(db, "lead_handler", {"channel": "web_chat", "contact": "dashboard-test", "name": body.name,
                                          "message": body.message})
    via = dispatch(run.id, background)
    return InboundOut(run_id=str(run.id), status=run.status.value, dispatched_via=via)
