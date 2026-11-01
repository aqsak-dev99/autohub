"""Daily Digest: a morning email summary of the last 24 hours for flowpath's team.

    schedule (n8n, 9 am) → collect → summarize → deliver

Code builds every number in the message; the LLM only writes one line on
what needs attention, from those numbers, and is told not to add any. If
the LLM call fails, the digest still goes out without that line. It goes to
DIGEST_EMAIL_TO; if delivery fails the text is still saved on the run for
n8n or the dashboard to show.
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


class Attention(BaseModel):
    line: str = Field(description="One or two short sentences on what the team should do first today. "
                                  "No numbers.")


ATTENTION_PROMPT = """You write the last line of a morning summary for a small marketing studio's team.
From the facts below, say in one or two short sentences what they should do first today (for example:
reply to a waiting hot lead, check failed runs). Do not include any numbers or names not given. No emojis."""


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

    return {
        "hours": hours,
        "leads": len(leads),
        "by_temperature": count("temperature"),
        "by_language": count("language"),
        "by_status": count("status"),
        "replied": len(replied),
        "auto_sent": sum(1 for lead in replied if lead.run_id not in reviewed_runs),
        "pending_approvals": len(pending),
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


def format_digest(stats: dict, attention: str | None, now: datetime, tz: str = "Asia/Karachi") -> str:
    local = now.astimezone(ZoneInfo(tz))
    t = stats["by_temperature"]
    lines = [f"flowpath digest · {local:%a %d %b}", ""]
    if stats["leads"] == 0:
        lines.append(f"No new leads in the last {stats['hours']} hours.")
    else:
        temps = ", ".join(f"{k} {t[k]}" for k in ("hot", "warm", "cold") if t.get(k))
        spam = stats["by_status"].get("spam", 0)
        lines.append(f"Leads: {stats['leads']}" + (f" ({temps})" if temps else "") + (f" · spam {spam}" if spam else ""))
        lines.append(f"Replied: {stats['replied']} ({stats['auto_sent']} auto-sent)")
    if stats["pending_approvals"]:
        lines.append(f"Waiting for review: {stats['pending_approvals']} (oldest {stats['oldest_pending_hours']} h)")
    for lead in stats["hot_leads"]:
        detail = ", ".join(filter(None, [" + ".join(lead["services"]) or None, lead["budget"]]))
        lines.append(f"🔥 {lead['name']}" + (f" · {detail}" if detail else "") + f" · {lead['status'].replace('_', ' ')}")
    lines.append(f"AI cost: ${stats['cost_usd']:.4f} · failed runs: {stats['failed_runs']}")
    if attention:
        lines += ["", f"→ {attention.strip()}"]
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
            s.output = stats

        with ctx.step("summarize") as s:
            attention = None
            if stats["leads"] or stats["pending_approvals"] or stats["failed_runs"]:
                try:
                    facts = {k: stats[k] for k in ("leads", "by_temperature", "replied", "auto_sent",
                                                   "pending_approvals", "oldest_pending_hours", "failed_runs")}
                    facts["hot_leads"] = stats["hot_leads"]
                    attention = s.llm_json(
                        [{"role": "system", "content": ATTENTION_PROMPT},
                         {"role": "user", "content": str(facts)}],
                        Attention, max_tokens=400,
                    ).parsed.line
                except Exception as exc:  # the numbers matter more than the advice line
                    s.output = {"fallback": True, "error": f"{type(exc).__name__}: {exc}"[:300]}
            else:
                s.skip("quiet day, nothing needs attention")
            text = format_digest(stats, attention, datetime.now(timezone.utc))
            s.output = {**(s.output or {}), "attention": attention, "text": text}

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
