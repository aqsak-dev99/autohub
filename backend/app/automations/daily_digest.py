"""Daily Digest: a morning email for flowpath's team: what happened, and what to do today.

    schedule (n8n, 9 am) → collect → summarize → deliver

collect: code counts everything (leads, replies, follow-ups, failures, cost) and builds a list of
concrete things someone could do today, each from a database row: "Check the reply waiting for Sana",
"Call Omar: he asked for a call", "Call Bilal yourself: no answer to the follow-up".

summarize: the AI only *orders* that list (top 3) and adds a short reason for each. It can't add a
task, a name or a number: it answers with task ids, unknown ids are dropped, and a reason that
contains a digit is dropped too. If the AI call fails, code orders the list by its own rules.
The email goes to DIGEST_EMAIL_TO; if delivery fails the text is still saved on the run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels import DeliveryError, send_reply
from app.engine.base import BaseAutomation, register
from app.engine.context import RunContext
from app.knowledge.flowpath import SERVICES
from app.models import Approval, ApprovalStatus, Lead, Run, RunStatus

SERVICE_SHORT = {s["id"]: s["name"].split(" ")[0].lower() for s in SERVICES}  # social, paid, search
BAND_SHORT = {"under_150k": "under Rs 150k", "150k_400k": "Rs 150k–400k", "400k_1m": "Rs 400k–1m",
              "over_1m": "over Rs 1m"}


class DigestIn(BaseModel):
    hours: int = Field(default=24, ge=1, le=24 * 7)
    source: str = "manual"


class Priority(BaseModel):
    id: str = Field(description="The id of one task from the list")
    why: str = Field(max_length=140, description="Why it matters today, in under 12 words. No numbers.")


class Priorities(BaseModel):
    items: list[Priority] = Field(max_length=3)


PRIORITIES_PROMPT = """You help the owner of a small marketing studio plan the morning.
Below is a list of tasks, each with an id. Pick the three that matter most today, most important first,
and give each a short reason (under 12 words). Money and momentum first: a hot lead waiting or asking
for a call beats a cold one; customers waiting beat internal checks.
Answer only with ids from the list. Don't add tasks, names or numbers. No emojis."""

TEMP_RANK = {"hot": 0, "warm": 1, "cold": 2}


def _since(db: Session, hours: int) -> datetime:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    # SQLite stores timestamps without a timezone; compare like with like
    return since.replace(tzinfo=None) if db.bind.dialect.name == "sqlite" else since


def collect_stats(db: Session, hours: int = 24) -> dict:
    """Every number in the digest, from the database. Also served by GET /api/digest/preview."""
    since = _since(db, hours)
    leads = db.scalars(select(Lead).where(Lead.created_at >= since)
                         .order_by(Lead.score.desc().nullslast(), Lead.created_at.desc())).all()
    reviewed_runs = set(db.scalars(select(Approval.run_id).where(Approval.created_at >= since)).all())

    def count(field: str) -> dict:
        out: dict[str, int] = {}
        for lead in leads:
            key = getattr(lead, field) or "unknown"
            out[key] = out.get(key, 0) + 1
        return out

    replied = [lead for lead in leads if lead.status == "replied"]
    pending = db.scalars(select(Approval).where(Approval.status == ApprovalStatus.pending)
                         .order_by(Approval.created_at)).all()
    oldest_wait_h = None
    if pending:
        created = pending[0].created_at
        created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        oldest_wait_h = round((datetime.now(timezone.utc) - created).total_seconds() / 3600, 1)

    runs = db.execute(
        select(func.count(Run.id), func.coalesce(func.sum(Run.total_cost_usd), 0.0))
        .where(Run.created_at >= since)
    ).one()
    failed = db.scalar(select(func.count(Run.id)).where(Run.created_at >= since, Run.status == RunStatus.failed))
    follow_ups_sent = db.scalar(select(func.count(Lead.id)).where(Lead.followed_up_at >= since)) or 0

    return {
        "hours": hours,
        "leads": len(leads),
        "by_temperature": count("temperature"),
        "by_language": count("language"),
        "by_status": count("status"),
        "replied": len(replied),
        "auto_sent": sum(1 for lead in replied if lead.run_id not in reviewed_runs),
        "pending_approvals": len(pending),
        "follow_ups_sent": follow_ups_sent,
        "follow_ups_waiting": sum(1 for a in pending if a.kind == "follow_up"),
        "oldest_pending_hours": oldest_wait_h,
        "hot_leads": [
            {"name": lead.name or lead.contact, "services": [SERVICE_SHORT.get(s, s) for s in lead.services or []],
             "budget": BAND_SHORT.get(lead.budget_band or ""), "status": lead.status}
            for lead in leads if lead.temperature == "hot"
        ][:5],
        "runs": runs[0],
        "failed_runs": failed or 0,
        "cost_usd": round(float(runs[1]), 5),
    }


def _hours_since(value: datetime, now: datetime) -> float:
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return (now - value).total_seconds() / 3600


def todo_candidates(db: Session, now: datetime | None = None) -> list[dict]:
    """Things someone could do today, each built from a row in the database. `rank` is code's own order."""
    now = now or datetime.now(timezone.utc)
    tasks: list[dict] = []

    for a in db.scalars(select(Approval).where(Approval.status == ApprovalStatus.pending)
                        .order_by(Approval.created_at).limit(6)):
        p = a.payload or {}
        temp, waited = p.get("temperature") or "cold", round(_hours_since(a.created_at, now))
        what = "follow-up" if a.kind == "follow_up" else "reply"
        tasks.append({"id": f"approve:{a.id}", "approval_id": a.id, "rank": TEMP_RANK.get(temp, 3) * 10,
                      "text": f"Check the {what} waiting for {p.get('name') or p.get('contact')}",
                      "detail": f"{temp} lead, waiting {waited} h" if temp in TEMP_RANK else f"waiting {waited} h"})

    recent = _since(db, 72)
    for lead in db.scalars(select(Lead).where(Lead.temperature == "hot", Lead.status == "replied",
                                              Lead.created_at >= recent, Lead.followed_up_at.is_(None))
                           .order_by(Lead.score.desc().nullslast()).limit(4)):
        if any("call" in r for r in lead.score_reasons or []):
            tasks.append({"id": f"call:{lead.id}", "run_id": str(lead.run_id) if lead.run_id else None, "rank": 5, "text": f"Call {lead.name or lead.contact}",
                          "detail": "hot lead, asked for a call"})

    quiet_since = _since(db, 48)
    for lead in db.scalars(select(Lead).where(Lead.temperature == "hot", Lead.followed_up_at.is_not(None),
                                              Lead.followed_up_at <= quiet_since).limit(3)):
        wrote_again = db.scalar(select(Lead.id).where(Lead.contact == lead.contact, Lead.id != lead.id,
                                                      Lead.created_at > lead.followed_up_at).limit(1))
        if not wrote_again:
            tasks.append({"id": f"quiet:{lead.id}", "run_id": str(lead.run_id) if lead.run_id else None, "rank": 15, "text": f"Call {lead.name or lead.contact} yourself",
                          "detail": "hot lead, no answer to the follow-up"})

    failed = db.scalar(select(func.count(Run.id)).where(Run.created_at >= _since(db, 24),
                                                        Run.status == RunStatus.failed)) or 0
    if failed:
        tasks.append({"id": "failed", "rank": 25, "text": "Look at the failed runs in AutoHub",
                      "detail": f"{failed} in the last 24 h"})
    return sorted(tasks, key=lambda t: t["rank"])


def pick_priorities(candidates: list[dict], answer: Priorities | None) -> list[dict]:
    """The AI's order where it's valid, code's order where it isn't. Never more than 3."""
    by_id = {c["id"]: c for c in candidates}
    chosen: list[dict] = []
    for item in (answer.items if answer else []):
        if item.id in by_id and all(c["id"] != item.id for c in chosen):
            why = item.why.strip() if item.why and not any(ch.isdigit() for ch in item.why) else None
            chosen.append({**by_id[item.id], "why": why})
    for c in candidates:  # top up from code's order (or fill it entirely if the AI failed)
        if len(chosen) >= 3:
            break
        if all(x["id"] != c["id"] for x in chosen):
            chosen.append({**c, "why": None})
    return chosen[:3]


def format_digest(stats: dict, todo: list[dict] | None, now: datetime, tz: str = "Asia/Karachi") -> str:
    local = now.astimezone(ZoneInfo(tz))
    t = stats["by_temperature"]
    lines = [f"flowpath digest · {local:%a %d %b}", ""]
    if todo:
        lines.append("Today:")
        for i, task in enumerate(todo, 1):
            lines.append(f"{i}. {task['text']} ({task['detail']})" + (f": {task['why'].rstrip('.')}" if task.get("why") else ""))
        lines.append("")
    if stats["leads"] == 0:
        lines.append(f"No new leads in the last {stats['hours']} hours.")
    else:
        temps = ", ".join(f"{k} {t[k]}" for k in ("hot", "warm", "cold") if t.get(k))
        spam = stats["by_status"].get("spam", 0)
        lines.append(f"Leads: {stats['leads']}" + (f" ({temps})" if temps else "") + (f" · spam {spam}" if spam else ""))
        lines.append(f"Replied: {stats['replied']} ({stats['auto_sent']} auto-sent)")
    if stats["pending_approvals"]:
        lines.append(f"Waiting for review: {stats['pending_approvals']} (oldest {stats['oldest_pending_hours']} h)")
    if stats.get("follow_ups_sent") or stats.get("follow_ups_waiting"):
        lines.append(f"Follow-ups: {stats.get('follow_ups_sent', 0)} sent, {stats.get('follow_ups_waiting', 0)} waiting for you")
    for lead in stats["hot_leads"]:
        detail = ", ".join(filter(None, [" + ".join(lead["services"]) or None, lead["budget"]]))
        lines.append(f"🔥 {lead['name']}" + (f" · {detail}" if detail else "") + f" · {lead['status'].replace('_', ' ')}")
    lines.append(f"AI cost: ${stats['cost_usd']:.4f} · failed runs: {stats['failed_runs']}")
    return "\n".join(lines)


@register
class DailyDigest(BaseAutomation):
    slug = "daily_digest"

    def run(self, ctx: RunContext, payload: dict) -> dict:
        settings = ctx.llm.settings
        with ctx.step("schedule", payload) as s:
            params = DigestIn.model_validate(payload)
            s.output = {"source": params.source, "hours": params.hours}

        with ctx.step("collect") as s:
            stats = collect_stats(ctx.db, params.hours)
            candidates = todo_candidates(ctx.db)
            s.output = {**stats, "candidates": candidates}

        with ctx.step("summarize", {"candidates": [c["id"] for c in candidates]}) as s:
            answer = None
            if len(candidates) > 1:  # one task needs no ordering
                try:
                    listing = "\n".join(f"{c['id']}: {c['text']} ({c['detail']})" for c in candidates)
                    answer = s.llm_json(
                        [{"role": "system", "content": PRIORITIES_PROMPT}, {"role": "user", "content": listing}],
                        Priorities, max_tokens=600,
                    ).parsed
                except Exception as exc:  # the list in code's order is still useful
                    s.output = {"fallback": True, "error": f"{type(exc).__name__}: {exc}"[:300]}
            elif not candidates:
                s.skip("nothing to do today")
            todo = pick_priorities(candidates, answer)
            text = format_digest(stats, todo, datetime.now(timezone.utc))
            s.output = {**(s.output or {}), "todo": todo,
                        "ai_ordered": bool(answer and any(t["why"] for t in todo)), "text": text}

        with ctx.step("deliver") as s:
            deliveries = []
            targets = [("email", settings.digest_email_to)]
            subject = text.splitlines()[0]  # "flowpath digest · Fri 30 Oct"
            for channel, to in targets:
                if not to:
                    continue
                try:
                    deliveries.append(send_reply(channel, to, text, settings, subject=subject))
                except DeliveryError as exc:
                    # best effort: the digest text is still saved on the run
                    deliveries.append({"channel": channel, "delivered": False, "mode": "error", "code": exc.code,
                                       "note": str(exc)})
            if not deliveries:
                deliveries.append({"delivered": False, "mode": "dry_run",
                                   "note": "set DIGEST_EMAIL_TO"})
            s.output = {"deliveries": deliveries}

        delivered = any(d.get("delivered") for d in deliveries)
        return {"text": text, "delivered": delivered}
