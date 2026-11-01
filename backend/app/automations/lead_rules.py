"""The Lead Handler's decisions, in plain code: lead score, price guard, routing.

Design rule: the LLM extracts facts (what service, what budget, how urgent);
code makes the decisions. That makes every score and every route explainable,
testable and identical for identical facts, with no model randomness.
"""
from __future__ import annotations

import re

from app.knowledge import flowpath

LANGUAGE_NAMES = {
    "english": "English",
    "roman_urdu": "Roman Urdu (Urdu written in English letters)",
    "urdu": "Urdu in Urdu script",
    "arabic": "Arabic",
    "other": "English",  # unsupported languages get an English reply, reviewed by a person
}

# short names for reasons shown in the inbox
LANGUAGE_LABELS = {"english": "English", "roman_urdu": "Roman Urdu", "urdu": "Urdu-script", "arabic": "Arabic",
                   "other": "Unsupported-language"}

SALES_INTENTS = {"new_business", "general_question"}


# ---------- lead score ----------

def budget_band(monthly_budget_pkr: int | None) -> str:
    if monthly_budget_pkr is None:
        return "unknown"
    for band_id, _label, low, high in flowpath.BUDGET_BANDS:
        if monthly_budget_pkr >= low and (high is None or monthly_budget_pkr < high):
            return band_id
    return "unknown"


BAND_POINTS = {"under_150k": 5, "150k_400k": 20, "400k_1m": 30, "over_1m": 35, "unknown": 0}
BAND_LABELS = {b[0]: b[1] for b in flowpath.BUDGET_BANDS}
URGENCY_POINTS = {"high": 15, "normal": 5, "low": 0}


def score_lead(intent: str, services: list[str], band: str, urgency: str,
               business_type: str | None, wants_call: bool) -> tuple[int, str, list[str]]:
    """Return (score 0–100, temperature, reasons). Every point has a reason the dashboard can show."""
    if intent not in SALES_INTENTS:
        return 0, "not_a_lead", [f"intent is {intent}, not a sales enquiry"]

    reasons: list[str] = []
    score = 0

    def add(points: int, why: str) -> None:
        nonlocal score
        if points:
            score += points
            reasons.append(f"+{points} {why}")

    add(30 if intent == "new_business" else 10, "wants to work with flowpath" if intent == "new_business"
        else "asking a general question")
    add(min(len(services), 2) * 10, f"interested in {len(services)} service(s)")
    add(BAND_POINTS.get(band, 0), f"budget {BAND_LABELS[band]}" if band in BAND_LABELS else "")
    add(URGENCY_POINTS.get(urgency, 0), f"{urgency} urgency")
    add(5 if business_type else 0, f"business type known ({business_type})")
    add(10 if wants_call else 0, "asked for a call or meeting")

    score = min(score, 100)
    temperature = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
    return score, temperature, reasons


# ---------- price guard ----------

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬", "01234567890123456789,")
_CURRENCY = r"(?:rs\.?|pkr|₨|rupees?|روپے|aed|usd|\$|sar|dirhams?|درهم|ريال)"
_UNIT = r"(lakh|lakhs|lac|lacs|k|thousand|million|mn|crore|لاکھ|ہزار)"
_AMOUNT = re.compile(
    # number: real thousands grouping (150,000 or Pakistani 1,50,000), or plain digits, optional decimals
    rf"(?P<cur>{_CURRENCY})?\s*(?P<num>\d{{1,3}}(?:,\d{{2,3}})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})?(?![a-z])",
    re.IGNORECASE,
)
_MULTIPLIER = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "لاکھ": 100_000,
               "k": 1_000, "thousand": 1_000, "ہزار": 1_000, "million": 1_000_000, "mn": 1_000_000,
               "crore": 10_000_000}


def money_amounts(text: str) -> set[int]:
    """Find money amounts in English, Roman Urdu, Urdu or Arabic text.

    Only counts a number as money when it has a currency, a unit (lakh, k...)
    or thousands separators, so "since 2019" or "15 minutes" is ignored.
    """
    found: set[int] = set()
    for m in _AMOUNT.finditer(text.translate(_DIGITS)):
        cur, num, unit = m.group("cur"), m.group("num"), (m.group("unit") or "").lower()
        if not (cur or unit or "," in num):
            continue
        try:
            value = float(num.replace(",", "")) * _MULTIPLIER.get(unit, 1)
        except ValueError:
            continue
        if value >= 1_000:
            found.add(int(round(value)))
    return found


def unsupported_prices(reply: str, knowledge_text: str) -> list[int]:
    """Amounts in the reply that never appear in the knowledge base."""
    allowed = money_amounts(knowledge_text)
    return sorted(money_amounts(reply) - allowed)


# ---------- routing ----------

def route_reply(*, judge_confidence: float, threshold: float, grounded: bool, unsupported_claims: list[str],
                language_matches: bool, language: str, review_languages: set[str], price_issues: list[int],
                intent: str, wants_unoffered_service: bool, check_prices: bool = True,
                check_existing_client: bool = True, check_unoffered_service: bool = True) -> list[str]:
    """Return the reasons a person must review this reply. Empty list means safe to auto-send.

    The check_* switches are the owner's choices on the Rules page; the other checks always apply."""
    reasons: list[str] = []
    if judge_confidence < threshold:
        reasons.append(f"confidence {judge_confidence:.2f} < {threshold:.2f}")
    if not grounded or unsupported_claims:
        claims = "; ".join(unsupported_claims[:3]) or "reply not supported by the knowledge base"
        reasons.append(f"unsupported claims: {claims}")
    if not language_matches:
        reasons.append("reply language doesn't match the customer's")
    if language == "other":
        reasons.append("customer wrote in a language AutoHub doesn't support yet")
    elif language in review_languages:
        reasons.append(f"{LANGUAGE_LABELS[language]} replies are reviewed until evals verify accuracy")
    if price_issues and check_prices:
        reasons.append("price not in knowledge base: " + ", ".join(f"Rs {p:,}" for p in price_issues))
    if intent == "existing_client" and check_existing_client:
        reasons.append("existing client: a person should handle this")
    if wants_unoffered_service and check_unoffered_service:
        reasons.append("asks for a service flowpath doesn't offer")
    return reasons


def replay_route(classify: dict, score: dict, rules) -> list[str]:
    """Re-decide a past reply under different rules, from what its run recorded (no AI calls).

    Used by the Rules page's "what if" preview. `classify` and `score` are the outputs
    the classify and score steps saved."""
    unsupported = [c["text"] for c in score.get("claims") or []
                   if c.get("kind") in {"fact_about_flowpath", "commitment"} and not c.get("supported")]
    return route_reply(
        judge_confidence=score.get("confidence") or 0.0, threshold=rules.auto_send_confidence,
        grounded=not unsupported, unsupported_claims=unsupported,
        language_matches=score.get("language_matches", True), language=classify.get("language", "other"),
        review_languages=set(rules.review_languages), price_issues=score.get("price_issues") or [],
        intent=classify.get("intent", ""), wants_unoffered_service=bool(classify.get("wants_unoffered_service")),
        check_prices=rules.review_price_not_on_site, check_existing_client=rules.review_existing_client,
        check_unoffered_service=rules.review_unoffered_service,
    )
