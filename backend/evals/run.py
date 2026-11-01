"""Evals: how well does the Lead Handler actually work, per language? Uses the real Groq models.

    docker compose exec api python -m evals.run              # everything (about 10 minutes on the free plan)
    docker compose exec api python -m evals.run --only checker --limit 4

Two sets, both hand-labelled, in evals/:
- leads.jsonl (40 messages, 10 per language): each goes through the full Lead Handler, exactly as
  in production, on a throwaway database. Scored on understanding (intent, language), extraction
  (services, budget), safety (nothing that must be reviewed is sent alone) and how many replies
  could go out on their own.
- checker.jsonl (16 replies): half contain a planted false claim (a guarantee, a made-up price,
  an office that doesn't exist). Scored on whether the fact check catches them, and how often it
  raises a false alarm on clean replies.

Writes evals/RESULTS.md (the summary in the README) and evals/results.json (every case).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGUAGES = ["english", "roman_urdu", "urdu", "arabic"]
LABEL = {"english": "English", "roman_urdu": "Roman Urdu", "urdu": "Urdu", "arabic": "Arabic"}
MIN_CASES_FOR_VERDICT = 8  # a recommendation off one or two messages would be noise


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- scoring (pure functions, unit-tested without any AI) ----------

def score_lead(case: dict, outcome: dict) -> dict:
    """Compare one Lead Handler run with its labels. `outcome` comes from `lead_outcome()`."""
    result = {"id": case["id"], "language": case["language"], "route": outcome["route"],
              "intent_ok": outcome["intent"] in case["intent"],
              # spam gets no reply, so the language it's in changes nothing: not scored
              "language_ok": None if case["intent"] == ["spam"] else outcome["language"] == case["language"],
              "seconds": outcome["seconds"], "cost_usd": outcome["cost_usd"], "fixed": outcome["fixed"],
              "error": outcome.get("error")}
    if "services" in case and outcome["route"] != "spam":
        expected, got = set(case["services"]), set(outcome["services"] or [])
        result["services_ok"] = got == set() if not expected else expected <= got
    if "budget_pkr" in case and outcome["route"] != "spam":
        result["budget_ok"] = outcome["budget_pkr"] == case["budget_pkr"]
    must_review = bool(case.get("must_review") or case.get("unoffered"))
    result["must_review"] = must_review
    result["unsafe"] = must_review and outcome["route"] == "auto"
    if case["intent"] == ["spam"]:
        result["spam_ok"] = outcome["route"] == "spam"
    return result


def score_checker(case: dict, flagged: bool, found: list[str]) -> dict:
    planted = bool(case["planted"])
    return {"id": case["id"], "language": case["language"], "planted": planted, "flagged": flagged,
            "caught": planted and flagged, "false_alarm": (not planted) and flagged, "found": found}


def _rate(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if key in r and r[key] is not None]
    return round(sum(bool(v) for v in values) / len(values), 3) if values else None


def summarize(lead_rows: list[dict], checker_rows: list[dict]) -> dict:
    summary: dict = {"languages": {}, "overall": {}}
    for scope, rows, checks in [("overall", lead_rows, checker_rows)] + [
            (lang, [r for r in lead_rows if r["language"] == lang], [c for c in checker_rows if c["language"] == lang])
            for lang in LANGUAGES]:
        replies = [r for r in rows if r["route"] in {"auto", "review"}]
        could_go_alone = [r for r in replies if not r["must_review"]]
        block = {
            "cases": len(rows),
            "intent": _rate(rows, "intent_ok"), "language": _rate(rows, "language_ok"),
            "services": _rate(rows, "services_ok"), "budget": _rate(rows, "budget_ok"),
            "unsafe_sends": sum(r["unsafe"] for r in rows),
            "auto_sent": round(sum(r["route"] == "auto" for r in could_go_alone) / len(could_go_alone), 3)
            if could_go_alone else None,
            "fixed_automatically": sum(bool(r["fixed"]) for r in rows),
            "median_seconds": round(statistics.median([r["seconds"] for r in replies]), 1) if replies else None,
            "cost_per_lead_usd": round(statistics.mean([r["cost_usd"] for r in rows]), 6) if rows else None,
            "errors": sum(bool(r.get("error")) for r in rows),
            "checker_catch": _rate([c for c in checks if c["planted"]], "caught"),
            "checker_false_alarm": _rate([c for c in checks if not c["planted"]], "false_alarm"),
            "checker_errors": sum(bool(c.get("error")) for c in checks),
        }
        (summary["overall"] if scope == "overall" else summary["languages"].setdefault(scope, {})).update(block)
    return summary


def pct(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)}%"


def report(summary: dict, model_info: str) -> str:
    """The Markdown summary for evals/RESULTS.md."""
    rows = [("Understood the request (intent)", "intent"), ("Detected the language", "language"),
            ("Picked out the services", "services"), ("Read the budget correctly", "budget"),
            ("Fact check caught a planted false claim", "checker_catch"),
            ("Fact check false alarms on clean replies", "checker_false_alarm"),
            ("Replies sent on their own (where allowed)", "auto_sent")]
    head = "| | " + " | ".join(LABEL[lang] for lang in LANGUAGES) + " | All |\n|---|" + "---|" * (len(LANGUAGES) + 1)
    lines = [head]
    for title, key in rows:
        cells = [pct(summary["languages"].get(lang, {}).get(key)) for lang in LANGUAGES] + [pct(summary["overall"].get(key))]
        lines.append(f"| {title} | " + " | ".join(cells) + " |")
    unsafe = [str(summary["languages"].get(lang, {}).get("unsafe_sends", 0)) for lang in LANGUAGES]
    lines.append("| **Sent alone when it should have asked** | " + " | ".join(unsafe) + f" | **{summary['overall']['unsafe_sends']}** |")
    o = summary["overall"]
    verdicts = []
    for lang in LANGUAGES:
        s = summary["languages"].get(lang, {})
        if not s.get("cases"):
            continue
        if s["cases"] < MIN_CASES_FOR_VERDICT:
            verdicts.append(f"- **{LABEL[lang]}:** only {s['cases']} message(s) in this run, too few to judge; "
                            "run the full set before changing the rules.")
            continue
        ready = (s.get("unsafe_sends") == 0 and (s.get("checker_catch") or 0) >= 0.9
                 and (s.get("checker_false_alarm") or 0) <= 0.25 and (s.get("intent") or 0) >= 0.85)
        verdicts.append(f"- **{LABEL[lang]}:** " + ("good enough to stop reviewing every reply by default."
                        if ready else "keep reviewing replies for now."))
    return "\n".join([
        "# Eval results", "",
        f"_Run {datetime.now(timezone.utc):%d %b %Y} · {model_info} · {o['cases']} messages, "
        f"{o['errors'] + o['checker_errors']} errors · median {o['median_seconds']} s per reply · about ${o['cost_per_lead_usd']} per message_", "",
        *lines, "",
        f"Replies rewritten automatically to remove an unsupported claim: {o['fixed_automatically']}.", "",
        "## What this says about the review rules", *verdicts, "",
        "How it's measured: `backend/evals/run.py`. Sets: `leads.jsonl` (40 labelled messages, 10 per language) "
        "and `checker.jsonl` (16 replies, half with a planted false claim).",
    ]) + "\n"


# ---------- running against the real models ----------

def lead_outcome(run, steps: dict) -> dict:
    """What happened in one Lead Handler run, in the shape score_lead() expects."""
    c = steps.get("classify")
    q = (steps.get("qualify").output or {}).get("extracted") or {} if steps.get("qualify") else {}
    route = "spam" if c and (c.output or {}).get("intent") == "spam" and "draft" not in steps else (
        "review" if "approval" in steps else "auto" if "send" in steps else "failed")
    revise = steps.get("revise")
    return {"route": route, "intent": (c.output or {}).get("intent") if c else None,
            "language": (c.output or {}).get("language") if c else None,
            "services": q.get("services"), "budget_pkr": q.get("monthly_budget_pkr"),
            "fixed": bool(revise and (revise.output or {}).get("removed") and not (revise.output or {}).get("error")),
            "seconds": sum(s.duration_ms for s in steps.values() if s.node_id != "approval") / 1000,
            "cost_usd": run.total_cost_usd, "error": run.error}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["leads", "checker"])
    parser.add_argument("--limit", type=int, help="run only the first N cases per language (quick check)")
    parser.add_argument("--delay", type=float, default=8, help="seconds between cases (Groq free plan: keep ~8)")
    args = parser.parse_args()

    # a throwaway database, so evals never touch real leads, and default rules
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/evals.db"
    os.environ["RUN_MODE"] = "inline"
    os.environ["SEND_MODE"] = "dry_run"
    sys.path.insert(0, str(HERE.parent))

    import app.automations  # noqa: F401
    from app.automations import lead_rules as rules
    from app.automations.lead_handler import JUDGE_PROMPT, PINNED_PASSAGES, Judgement, grounding
    from app.db import SessionLocal, init_db
    from app.engine import executor
    from app.knowledge import get_kb
    from app.llm.client import get_llm
    from app.models import Run
    from app.registry import seed_automations

    llm = get_llm()
    if not llm.settings.groq_api_key:
        sys.exit("GROQ_API_KEY isn't set: evals use the real models.")
    init_db()
    with SessionLocal() as db:
        seed_automations(db)

    def pick(cases, split_by=None):
        """--limit N: the first N per language (and per half, so a quick run still has planted claims)."""
        if not args.limit:
            return cases
        groups = [[c for c in cases if bool(c.get(split_by)) == flag] for flag in (True, False)] if split_by else [cases]
        return [c for lang in LANGUAGES for group in groups for c in [x for x in group if x["language"] == lang][: args.limit]]

    lead_rows, checker_rows = [], []
    if args.only != "checker":
        cases = pick(load("leads.jsonl"))
        for i, case in enumerate(cases, 1):
            payload = {"channel": "web_form", "contact": f"eval-{case['id']}@example.com", "name": "Eval", "message": case["message"]}
            with SessionLocal() as db:
                run_id = executor.create_run(db, "lead_handler", payload).id
            executor.execute_run(run_id, llm=llm)
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                row = score_lead(case, lead_outcome(run, {s.node_id: s for s in run.steps}))
            lead_rows.append(row)
            flags = [k for k in ("intent_ok", "language_ok", "services_ok", "budget_ok") if row.get(k) is False]
            print(f"[{i}/{len(cases)}] {case['id']:6} {row['route']:6} {'UNSAFE ' if row['unsafe'] else ''}"
                  f"{'missed: ' + ', '.join(flags) if flags else 'ok'}{' ERROR ' + row['error'][:80] if row['error'] else ''}")
            time.sleep(args.delay)

    if args.only != "leads":
        kb = get_kb()
        cases = pick(load("checker.jsonl"), split_by="planted")
        for i, case in enumerate(cases, 1):
            hits = kb.search(case["message"], limit=4)
            found_ids = {p.id for p, _ in hits}
            passages = [p for p, _ in hits] + [kb.by_id[pid] for pid in PINNED_PASSAGES if pid not in found_ids]
            passages_text = "\n\n".join(f"[{p.id}] {p.title}\n{p.text}" for p in passages)
            try:
                j = llm.complete_json(
                    [{"role": "system", "content": JUDGE_PROMPT.format(language=LABEL[case["language"]])},
                     {"role": "user", "content": f"Passages:\n{passages_text}\n\nCustomer message:\n{case['message']}"
                                                 f"\n\nReply to check:\n{case['reply']}"}],
                    Judgement, max_tokens=3000, reasoning_effort="medium").parsed
                _, unsupported = grounding(j)
                error = None
            except Exception as exc:  # one broken answer is a result to report, not a reason to stop
                unsupported, error = [], f"{type(exc).__name__}: {exc}"[:200]
            prices = rules.unsupported_prices(case["reply"], kb.full_text() + "\n" + case["message"])
            row = score_checker(case, bool(unsupported or prices), unsupported + [f"Rs {p:,}" for p in prices])
            row["error"] = error
            checker_rows.append(row)
            print(f"[{i}/{len(cases)}] {case['id']:12} {'caught' if row['caught'] else 'FALSE ALARM' if row['false_alarm'] else 'missed' if row['planted'] else 'clean ok'}")
            time.sleep(args.delay / 2)

    summary = summarize(lead_rows, checker_rows)
    model_info = f"{llm.settings.groq_text_model} + {llm.settings.groq_draft_model}"
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "leads": lead_rows, "checker": checker_rows},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "RESULTS.md").write_text(report(summary, model_info), encoding="utf-8")
    print("\n" + report(summary, model_info))


if __name__ == "__main__":
    main()
