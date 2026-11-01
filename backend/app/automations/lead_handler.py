"""Lead Handler: turns an incoming message into a qualified lead and a grounded reply.

    intake → classify → retrieve → qualify → draft → score ─┬─ high → send ──────┬→ save_lead
               │                                             └─ low → approval ──┤ (approved/edited)
               └──────────────── spam ───────────────────────────────────────────┘ (rejected skips send)

Four LLM calls (classify, qualify, draft, judge). Everything that *decides*
something (lead score, price check, auto-send vs review) is plain code in
lead_rules.py, so decisions are explainable and testable.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.channels import reply_subject, send_reply
from app.engine.base import BaseAutomation, NeedsApproval, register
from app.rules_store import get_rules
from app.engine.context import RunContext
from app.knowledge import get_kb
from app.knowledge.flowpath import SERVICE_IDS
from app.automations import lead_rules as rules
from app.models import ApprovalStatus, Lead

Language = Literal["english", "roman_urdu", "urdu", "arabic", "other"]
Intent = Literal["new_business", "general_question", "existing_client", "job_applicant", "vendor_or_partnership", "spam"]
ServiceId = Literal["social-media", "paid-advertising", "seo"]


# Passages the draft rules depend on ("say which services flowpath offers", "the fee is quoted after the
# audit", "the audit confirms scope"). They're always given to the model, whatever the search returns, so the prompt never asks for a
# fact the model can't see. Found in testing: without them the model invented "web design" as a service.
PINNED_PASSAGES = ("services-overview", "faq-0", "process")


# ---------- input ----------

class LeadIn(BaseModel):
    channel: Literal["email", "web_form", "web_chat"]
    contact: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    # email only: keep the reply in the customer's thread
    subject: str | None = Field(default=None, max_length=300)
    in_reply_to: str | None = Field(default=None, max_length=500)


# ---------- what each LLM step must return ----------

class Classification(BaseModel):
    intent: Intent
    language: Language
    search_query: str = Field(description="The customer's need rewritten as a short English search query")
    asks_price: bool
    wants_unoffered_service: bool = Field(description="True if they want something other than social media, "
                                                      "paid advertising or search/SEO (e.g. an app or a website build)")
    confidence: float = Field(ge=0, le=1)


class Qualification(BaseModel):
    services: list[ServiceId] = Field(default_factory=list)
    business_type: str | None = Field(default=None, description="Short English description, e.g. 'clothing brand'")
    monthly_budget_pkr: int | None = Field(default=None, description="Monthly budget in PKR if stated, else null")
    timeline: str | None = Field(default=None, description="When they want to start, short English, else null")
    urgency: Literal["high", "normal", "low"] = "normal"
    wants_call: bool = False


class Draft(BaseModel):
    reply: str
    used_passage_ids: list[str] = Field(default_factory=list)


ClaimKind = Literal["fact_about_flowpath", "commitment", "restates_customer", "courtesy"]


class Claim(BaseModel):
    text: str
    kind: ClaimKind
    supported: bool = Field(description="True if the passages support it (always true for restates_customer "
                                        "and courtesy)")


class Judgement(BaseModel):
    """The judge only labels claims. Code decides what counts (see grounding())."""
    claims: list[Claim] = Field(default_factory=list)
    language_matches: bool


NEEDS_SUPPORT = {"fact_about_flowpath", "commitment"}


def grounding(j: "Judgement") -> tuple[float, list[str]]:
    """(share of claims needing support that are supported, the unsupported ones). 1.0 if nothing needs support."""
    checked = [c for c in j.claims if c.kind in NEEDS_SUPPORT]
    unsupported = [c.text for c in checked if not c.supported]
    if not checked:
        return 1.0, []
    return round((len(checked) - len(unsupported)) / len(checked), 2), unsupported


# ---------- prompts ----------

CLASSIFY_PROMPT = """You triage messages sent to flowpath, a digital marketing studio in Lahore that offers
exactly three services: social media, paid advertising (Meta, TikTok, Google ads) and search/SEO.

intent:
- new_business: wants marketing help or is considering hiring flowpath
- general_question: asks about flowpath (location, process, contracts) without a clear project
- existing_client: already works with flowpath and needs help with ongoing work
- job_applicant: asking about jobs or internships
- vendor_or_partnership: selling something to flowpath or proposing a partnership
- spam: scams, prizes, links, gibberish

language (of the customer's message):
- english
- roman_urdu: Urdu written in English letters, including English mixed with Roman Urdu
- urdu: Urdu in Urdu (Arabic) script
- arabic: the Arabic language
- other: anything else

search_query: their need as a short English search query for flowpath's website content.
confidence: how sure you are about the intent, 0 to 1."""

QUALIFY_PROMPT = """Extract sales facts from a message sent to flowpath, a digital marketing studio.
Only extract what the customer actually said; use null when something isn't stated.
- services: any of social-media, paid-advertising, seo that they want
- monthly_budget_pkr: convert to a whole number of Pakistani rupees (1 lakh = 100000, 50k = 50000)
- urgency: high = within two weeks or urgent; normal = within about three months; low = just exploring
- wants_call: true if they ask for a call or meeting"""

DRAFT_PROMPT = """You write replies for flowpath, a digital marketing studio in Lahore.

Rules:
- Write in {language}. Match the customer's style: if they mixed English and Urdu, mix them the same way.
- Use ONLY facts from the passages. If something isn't covered, say a team member will confirm it.
- Never invent a price, discount or guarantee. You may share the published price range from the passages and
  say the fixed monthly fee is quoted after the audit.
- If they want a service flowpath doesn't offer, say honestly which three services flowpath offers. Never offer,
  hint at or "explore" building apps, websites or anything else.
- Don't promise start dates, results, or that their budget is enough. You may repeat what they told you
  ("you mentioned a budget of...") and say the audit confirms scope and fee.
- Job applicants: point them to the open roles and the email address in the passages.
- Existing clients: thank them and say a team member will get back to them. Don't promise when.
- End with one clear next step, such as a 15-minute call or sharing their Instagram or website.
- Under {max_words} words. Warm and professional. At most one emoji. Sign off as "Team flowpath".
- Never mention other clients by name unless it's a case study in the passages.

Return the reply and the ids of the passages you used."""

JUDGE_PROMPT = """You check a reply before it is sent to a customer of flowpath, a marketing studio.

List every claim in the reply and label its kind:
- fact_about_flowpath: anything stated about flowpath: services, prices, process, contracts, timelines,
  results, case studies, location, contact details, hours
- commitment: flowpath agreeing to or promising something: a start date, that their budget is enough,
  guaranteed results, a discount, a specific deliverable for them
- restates_customer: repeating what the customer said about themselves ("you mentioned a budget of 1.5 lakh",
  "for your restaurant in DHA")
- courtesy: greetings, thanks, sign-offs, asking a question, offering a call or meeting, saying a team member
  will follow up or confirm details

supported: true only if the passages back it up. restates_customer and courtesy are always supported.
language_matches: the reply is written in {language}, matching the customer's message."""


@register
class LeadHandler(BaseAutomation):
    slug = "lead_handler"

    def run(self, ctx: RunContext, payload: dict) -> dict:
        settings = ctx.llm.settings
        kb = get_kb()

        # 1. intake: validate and store the raw message, so the lead exists even while waiting for a human
        with ctx.step("intake", payload) as s:
            inbound = LeadIn.model_validate(payload)
            # a retried run keeps the lead it created the first time
            lead = ctx.db.query(Lead).filter_by(run_id=ctx.run.id).one_or_none()
            if lead is None:
                lead = Lead(run_id=ctx.run.id, channel=inbound.channel, contact=inbound.contact,
                            name=inbound.name, message=inbound.message)
                ctx.db.add(lead)
            lead.status = "new"
            ctx.db.commit()
            s.output = {"lead_id": lead.id, "characters": len(inbound.message)}

        # 2. classify: intent, language, and an English search query
        with ctx.step("classify", {"message": inbound.message}) as s:
            c: Classification = s.llm_json(
                [{"role": "system", "content": CLASSIFY_PROMPT},
                 {"role": "user", "content": inbound.message}],
                Classification, max_tokens=400,
            ).parsed
            lead.intent, lead.language = c.intent, c.language
            s.output = c

        if c.intent == "spam" and c.confidence >= 0.8:
            with ctx.step("save_lead") as s:
                lead.status = "spam"
                s.output = {"lead_id": lead.id, "status": "spam", "replied": False}
            return {"lead_id": lead.id, "route": "spam"}

        # 3. retrieve: keyword search over flowpath's content
        query = c.search_query.strip() or inbound.message
        with ctx.step("retrieve", {"query": query}) as s:
            hits = kb.search(query, limit=4)
            found = {p.id for p, _ in hits}
            pinned = [(kb.by_id[pid], None) for pid in PINNED_PASSAGES if pid not in found]
            hits = hits + pinned
            s.output = {"kb_version": kb.version,
                        "passages": [{"id": p.id, "label": p.label, "url": p.url, "score": sc,
                                      "pinned": sc is None} for p, sc in hits]}

        # 4. qualify: the LLM extracts facts, code computes the score
        with ctx.step("qualify") as s:
            if c.intent in rules.SALES_INTENTS:
                q: Qualification = s.llm_json(
                    [{"role": "system", "content": QUALIFY_PROMPT},
                     {"role": "user", "content": inbound.message}],
                    Qualification, max_tokens=400,
                ).parsed
            else:
                q = Qualification(urgency="low")
            band = rules.budget_band(q.monthly_budget_pkr)
            score, temperature, reasons = rules.score_lead(
                c.intent, q.services, band, q.urgency, q.business_type, q.wants_call)
            lead.services, lead.business_type = q.services, q.business_type
            lead.monthly_budget_pkr, lead.budget_band, lead.timeline = q.monthly_budget_pkr, band, q.timeline
            lead.score, lead.temperature, lead.score_reasons = score, temperature, reasons
            if c.intent not in rules.SALES_INTENTS:
                s.skip(f"{c.intent} is not a sales enquiry")
            s.output = {**(s.output or {}), "extracted": q, "budget_band": band, "score": score,
                        "temperature": temperature, "reasons": reasons}

        passages_text = "\n\n".join(f"[{p.id}] {p.title}\n{p.text}" for p, _ in hits) or "(no passages found)"
        language_name = rules.LANGUAGE_NAMES[c.language]
        max_words = 90 if inbound.channel == "web_chat" else 150  # chat replies are read on a phone-sized widget

        # 5. draft the reply with the stronger model
        with ctx.step("draft", {"language": c.language, "passages": [p.id for p, _ in hits]}) as s:
            d: Draft = s.llm_json(
                [{"role": "system", "content": DRAFT_PROMPT.format(language=language_name, max_words=max_words)},
                 {"role": "user", "content": f"Customer name: {inbound.name or 'unknown'}\n"
                                             f"Channel: {inbound.channel}\nIntent: {c.intent}\n\n"
                                             f"Passages:\n{passages_text}\n\nCustomer message:\n{inbound.message}"}],
                Draft, model=settings.groq_draft_model, temperature=0.3, max_tokens=900,
            ).parsed
            s.output = d

        # 6. score: an LLM judge checks grounding, then code applies the routing rules
        with ctx.step("score") as s:
            j: Judgement = s.llm_json(
                [{"role": "system", "content": JUDGE_PROMPT.format(language=language_name)},
                 {"role": "user", "content": f"Passages:\n{passages_text}\n\nCustomer message:\n{inbound.message}"
                                             f"\n\nReply to check:\n{d.reply}"}],
                # reasoning shares the output budget with the JSON answer, so give it room: a cut-off
                # answer is invalid JSON (found in testing on long Arabic and English replies)
                Judgement, max_tokens=3000, reasoning_effort="medium",
            ).parsed
            confidence, unsupported = grounding(j)
            # amounts the customer gave (their own budget) aren't invented, so they're allowed too
            price_issues = rules.unsupported_prices(d.reply, kb.full_text() + "\n" + inbound.message)
            owner = get_rules(ctx.db, settings)  # the Rules page; env values are the defaults
            review_reasons = rules.route_reply(
                judge_confidence=confidence, threshold=owner.auto_send_confidence, grounded=not unsupported,
                unsupported_claims=unsupported, language_matches=j.language_matches,
                language=c.language, review_languages=set(owner.review_languages),
                price_issues=price_issues, intent=c.intent, wants_unoffered_service=c.wants_unoffered_service,
                check_prices=owner.review_price_not_on_site, check_existing_client=owner.review_existing_client,
                check_unoffered_service=owner.review_unoffered_service,
            )
            route = "review" if review_reasons else "auto"
            lead.confidence = confidence
            s.output = {"claims": j.claims, "language_matches": j.language_matches, "confidence": confidence,
                        "price_issues": price_issues, "route": route, "reasons": review_reasons}

        if route == "review":
            with ctx.step("approval", {"reasons": review_reasons}) as s:
                lead.status = "awaiting_approval"
                lead.reply = d.reply
                s.output = {"status": "waiting for a person"}
                raise NeedsApproval(
                    kind="reply_draft",
                    reason="; ".join(review_reasons),
                    payload={
                        "lead_id": lead.id, "channel": inbound.channel, "contact": inbound.contact,
                        "name": inbound.name, "message": inbound.message, "language": c.language,
                        "intent": c.intent, "reply": d.reply, "confidence": confidence,
                        "reasons": review_reasons, "temperature": temperature, "score": score,
                        "qualification": {"services": q.services, "business_type": q.business_type,
                                          "monthly_budget_pkr": q.monthly_budget_pkr, "budget_band": band,
                                          "timeline": q.timeline},
                        "passages": [{"id": p.id, "label": p.label, "url": p.url, "score": sc} for p, sc in hits],
                    },
                    output={"lead_id": lead.id, "route": "review", "temperature": temperature},
                )

        delivery = self._send(ctx, inbound.channel, inbound.contact, d.reply)
        self._save(ctx, lead, d.reply, delivery, status="replied")
        return {"lead_id": lead.id, "route": "auto", "temperature": temperature, "score": score}

    def resume(self, ctx: RunContext, payload: dict, approval) -> dict:
        lead = ctx.db.get(Lead, approval.payload["lead_id"])
        final = approval.final_payload or {}
        ctx.finish_waiting_step("approval", {"decision": approval.status.value,
                                             "similarity": final.get("similarity"), "note": final.get("note")})

        if approval.status == ApprovalStatus.rejected:
            with ctx.step("save_lead") as s:
                lead.status = "rejected"
                lead.updated_at = datetime.now(timezone.utc)
                s.output = {"lead_id": lead.id, "status": "rejected", "replied": False}
            return {"lead_id": lead.id, "route": "review", "decision": "rejected"}

        reply = final.get("reply") or approval.payload["reply"]
        delivery = self._send(ctx, lead.channel, lead.contact, reply)
        self._save(ctx, lead, reply, delivery, status="replied")
        return {"lead_id": lead.id, "route": "review", "decision": approval.status.value}

    def on_failure(self, ctx: RunContext, error: Exception) -> None:
        lead = ctx.db.query(Lead).filter_by(run_id=ctx.run.id).one_or_none()
        if lead is not None:
            lead.status = "failed"

    # ---------- shared tail ----------

    @staticmethod
    def _send(ctx: RunContext, channel: str, contact: str, reply: str) -> dict:
        with ctx.step("send", {"channel": channel}) as s:
            settings = ctx.llm.settings
            payload = ctx.run.input or {}
            # dry run, a real send, or a DeliveryError that fails the step (and the run) visibly
            s.output = send_reply(
                channel, contact, reply, settings,
                subject=reply_subject(payload.get("subject"), f"Your enquiry to {settings.email_from_name}"),
                in_reply_to=payload.get("in_reply_to"),
            )
            return s.output

    @staticmethod
    def _save(ctx: RunContext, lead: Lead, reply: str, delivery: dict, status: str) -> None:
        with ctx.step("save_lead") as s:
            lead.reply = reply
            lead.replied = True
            lead.status = status
            lead.updated_at = datetime.now(timezone.utc)
            s.output = {"lead_id": lead.id, "status": status, "delivery_mode": delivery["mode"]}


def edit_similarity(draft: str, final: str) -> float:
    """1.0 = sent exactly as drafted. Feeds the edit-rate metric and Phase 6 evals."""
    return round(difflib.SequenceMatcher(None, draft.strip(), final.strip()).ratio(), 3)


assert set(SERVICE_IDS) == {"social-media", "paid-advertising", "seo"}, "ServiceId must match flowpath's services"
