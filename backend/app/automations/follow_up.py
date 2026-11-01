"""Follow-up Nudge: one gentle follow-up when a good lead goes quiet after our reply.

    scan (n8n, daily) → one run per quiet lead:
    pick → retrieve → draft → score ─┬─ auto → send ─────────┬→ save
                                     └─ review → (translate) → approval ┘ (rejected: nothing sent)

A lead is due when it is hot or warm, we replied by email at least FOLLOW_UP_AFTER_DAYS ago
(but not more than FOLLOW_UP_MAX_AGE_DAYS), and the customer hasn't written again since. Each
lead gets at most one follow-up, ever: the scan claims `follow_up:<lead id>` in inbound_messages,
whose unique key makes a second claim fail, even if two scans overlap. A follow-up the owner
skips is never offered again.

The draft goes through the same fact check and the same Rules page as the Lead Handler's
replies, so a follow-up can't promise what a first reply couldn't.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, exists, literal, select
from sqlalchemy.orm import Session, aliased

from app.automations import lead_rules as rules
from app.automations.lead_handler import (Draft, Translation, TRANSLATE_PROMPT, decide_route, judge_reply,
                                          passages_block, with_pinned)
from app.channels import reply_subject, send_reply
from app.config import Settings
from app.engine.base import BaseAutomation, NeedsApproval, register
from app.engine.context import RunContext
from app.knowledge import get_kb
from app.models import ApprovalStatus, InboundMessage, Lead, Run
from app.rules_store import get_rules

FOLLOW_UP_CHANNELS = ("email", "web_form")  # the ones we can write to later; website chat can't
FOLLOW_UP_TEMPERATURES = ("hot", "warm")


class FollowUpIn(BaseModel):
    lead_id: int


FOLLOW_UP_PROMPT = """You write a short follow-up for flowpath, a digital marketing studio in Lahore.

flowpath already replied to this customer's enquiry, and they haven't written back. Write one gentle
follow-up message:
- Write in {language}. Match the customer's style, as in their message.
- Refer briefly to what they asked about, so they remember the conversation.
- Make the next step easy: one simple question or a 15-minute call. No pressure, no urgency, no guilt.
- Do NOT repeat the whole earlier reply. Do NOT add new facts, prices, discounts, dates or promises; use only
  facts from the passages, and only if needed.
- Under 70 words. Warm and brief. No emoji. Sign off as "Team flowpath".

Return the message and the ids of the passages you used."""


def _naive_if_sqlite(db: Session, value: datetime) -> datetime:
    return value.replace(tzinfo=None) if db.bind.dialect.name == "sqlite" else value


def due_leads_query(db: Session, settings: Settings, now: datetime | None = None):
    """Leads that should get a follow-up now. Everything is checked in SQL, in one query."""
    now = now or datetime.now(timezone.utc)
    quiet_since = _naive_if_sqlite(db, now - timedelta(days=settings.follow_up_after_days))
    too_old = _naive_if_sqlite(db, now - timedelta(days=settings.follow_up_max_age_days))
    later = aliased(Lead)
    return (
        select(Lead)
        .where(Lead.status == "replied", Lead.replied.is_(True), Lead.followed_up_at.is_(None),
               Lead.temperature.in_(FOLLOW_UP_TEMPERATURES), Lead.channel.in_(FOLLOW_UP_CHANNELS),
               Lead.replied_at <= quiet_since, Lead.replied_at >= too_old)
        # they wrote again since our reply: that's a new conversation, not a quiet lead
        .where(~exists().where(and_(later.contact == Lead.contact, later.id != Lead.id,
                                    later.created_at > Lead.replied_at)))
        # already followed up, or the owner skipped it
        .where(~exists().where(InboundMessage.external_id == literal("follow_up:") + cast(Lead.id, String)))
        .order_by(Lead.score.desc().nullslast(), Lead.replied_at)
    )


def why_not_due(db: Session, lead: Lead) -> str | None:
    """Re-checked when the run starts, because time passes between the scan and the run."""
    if lead.followed_up_at is not None:
        return "already followed up"
    if lead.status != "replied":
        return f"lead is {lead.status}"
    newer = db.scalar(select(Lead.id).where(Lead.contact == lead.contact, Lead.id != lead.id,
                                            Lead.created_at > lead.replied_at).limit(1))
    return "the customer wrote again" if newer else None


def days_between(start: datetime | None, end: datetime) -> float | None:
    if start is None:
        return None
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    return round((end - start).total_seconds() / 86400, 1)


@register
class FollowUpNudge(BaseAutomation):
    slug = "follow_up"
    irreversible_steps = frozenset({"send"})

    def run(self, ctx: RunContext, payload: dict) -> dict:
        settings = ctx.llm.settings
        kb = get_kb()

        # 1. pick: load the lead and its first conversation; stop if it no longer needs a nudge
        with ctx.step("pick", payload) as s:
            params = FollowUpIn.model_validate(payload)
            lead = ctx.db.get(Lead, params.lead_id)
            if lead is None:
                raise ValueError(f"lead {params.lead_id} not found")
            original = ctx.db.get(Run, lead.run_id).input if lead.run_id else {}
            quiet = days_between(lead.replied_at, datetime.now(timezone.utc))
            reason = why_not_due(ctx.db, lead)
            s.output = {"lead_id": lead.id, "name": lead.name, "temperature": lead.temperature,
                        "language": lead.language, "days_quiet": quiet}
            if reason:
                s.skip(reason)
                s.output = {**s.output, "skipped": reason}
        if reason:
            return {"lead_id": lead.id, "route": "skipped", "reason": reason}

        language = lead.language if lead.language in rules.LANGUAGE_NAMES else "english"
        language_name = rules.LANGUAGE_NAMES[language]

        # 2. retrieve: the same passages a reply to their first message would use
        with ctx.step("retrieve", {"query": lead.message[:300]}) as s:
            hits = with_pinned(kb, kb.search(lead.message, limit=3))
            s.output = {"kb_version": kb.version,
                        "passages": [{"id": p.id, "label": p.label, "url": p.url, "score": sc,
                                      "pinned": sc is None} for p, sc in hits]}
        passages_text = passages_block(hits)

        # 3. draft the follow-up with the stronger model
        with ctx.step("draft", {"language": language, "days_quiet": quiet}) as s:
            d: Draft = s.llm_json(
                [{"role": "system", "content": FOLLOW_UP_PROMPT.format(language=language_name)},
                 {"role": "user", "content": f"Customer name: {lead.name or 'unknown'}\n"
                                             f"Days since our reply: {quiet}\n\nPassages:\n{passages_text}\n\n"
                                             f"Their message:\n{lead.message}\n\nOur earlier reply:\n{lead.reply}"}],
                Draft, model=settings.groq_draft_model, temperature=0.4, max_tokens=700,
            ).parsed
            s.output = d

        # 4. score: the Lead Handler's fact check and the owner's rules, unchanged
        owner = get_rules(ctx.db, settings)
        with ctx.step("score") as s:
            j = judge_reply(s, language_name, passages_text, lead.message, d.reply)
            verdict = decide_route(j, d.reply, owner=owner, known_text=kb.full_text() + "\n" + lead.message,
                                   language=language, intent=lead.intent or "new_business",
                                   wants_unoffered_service=False)
            s.output = verdict
        route, reasons = verdict["route"], verdict["reasons"]

        # 5. translate for the owner when they'll review a reply in Urdu or Arabic
        translation = None
        if route == "review" and language != "english":
            with ctx.step("translate") as s:
                try:
                    translation = s.llm_json(
                        [{"role": "system", "content": TRANSLATE_PROMPT},
                         {"role": "user", "content": f"Customer message:\n{lead.message}\n\nReply:\n{d.reply}"}],
                        Translation, max_tokens=1000,
                    ).parsed.model_dump()
                    s.output = translation
                except Exception as exc:  # approving without a translation is still possible
                    s.output = {"error": f"{type(exc).__name__}: {exc}"[:300]}

        if route == "review":
            with ctx.step("approval", {"reasons": reasons}) as s:
                s.output = {"status": "waiting for a person"}
                raise NeedsApproval(
                    kind="follow_up",
                    reason="; ".join(reasons),
                    payload={
                        "lead_id": lead.id, "channel": lead.channel, "contact": lead.contact, "name": lead.name,
                        "message": lead.message, "language": language, "intent": lead.intent,
                        "reply": d.reply, "confidence": verdict["confidence"], "reasons": reasons,
                        "temperature": lead.temperature, "score": lead.score,
                        "qualification": {"services": lead.services or [], "business_type": lead.business_type,
                                          "monthly_budget_pkr": lead.monthly_budget_pkr,
                                          "budget_band": lead.budget_band or "unknown", "timeline": lead.timeline},
                        "passages": [{"id": p.id, "label": p.label, "url": p.url, "score": sc} for p, sc in hits],
                        "translation": translation,
                        "follow_up": {"days_quiet": quiet, "previous_reply": lead.reply,
                                      # the first conversation, where the dashboard shows the whole thread
                                      "conversation_run_id": str(lead.run_id) if lead.run_id else None},
                    },
                    output={"lead_id": lead.id, "route": "review"},
                )

        self._send(ctx, lead, original, d.reply)
        return {"lead_id": lead.id, "route": "auto", "days_quiet": quiet}

    def resume(self, ctx: RunContext, payload: dict, approval) -> dict:
        lead = ctx.db.get(Lead, approval.payload["lead_id"])
        final = approval.final_payload or {}
        ctx.finish_waiting_step("approval", {"decision": approval.status.value,
                                             "similarity": final.get("similarity"), "note": final.get("note")})
        if approval.status == ApprovalStatus.rejected:
            with ctx.step("save") as s:
                s.output = {"lead_id": lead.id, "followed_up": False, "note": "skipped by the owner; not offered again"}
            return {"lead_id": lead.id, "route": "review", "decision": "rejected"}
        original = ctx.db.get(Run, lead.run_id).input if lead.run_id else {}
        self._send(ctx, lead, original, final.get("reply") or approval.payload["reply"])
        return {"lead_id": lead.id, "route": "review", "decision": approval.status.value}

    @staticmethod
    def _send(ctx: RunContext, lead: Lead, original: dict, reply: str) -> None:
        settings = ctx.llm.settings
        with ctx.step("send", {"channel": lead.channel}) as s:
            # in the customer's original email thread, so they see it under our first reply
            s.output = send_reply(
                lead.channel, lead.contact, reply, settings,
                subject=reply_subject(original.get("subject"), f"Your enquiry to {settings.email_from_name}"),
                in_reply_to=original.get("in_reply_to"),
            )
            delivery = s.output
        with ctx.step("save") as s:
            lead.followed_up_at = lead.updated_at = datetime.now(timezone.utc)
            lead.follow_up_reply = reply
            s.output = {"lead_id": lead.id, "followed_up": True, "delivery_mode": delivery["mode"]}
