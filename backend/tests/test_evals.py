"""The eval datasets are well-formed, and the scoring is right. (The evals themselves need Groq.)"""
from evals.run import LANGUAGES, load, report, score_checker, score_lead, summarize

INTENTS = {"new_business", "general_question", "existing_client", "job_applicant", "vendor_or_partnership", "spam"}
SERVICES = {"social-media", "paid-advertising", "seo"}


def test_lead_set_is_balanced_and_valid():
    cases = load("leads.jsonl")
    assert len({c["id"] for c in cases}) == len(cases) == 40
    for lang in LANGUAGES:
        assert sum(c["language"] == lang for c in cases) == 10
    for c in cases:
        assert set(c["intent"]) <= INTENTS and c["message"].strip()
        assert set(c.get("services", [])) <= SERVICES
        if c["language"] in {"urdu", "arabic"} and c["intent"] != ["spam"]:
            assert c.get("must_review"), f"{c['id']}: the default rules review every {c['language']} reply"


def test_checker_set_is_half_planted():
    cases = load("checker.jsonl")
    assert len(cases) == 16 and sum(bool(c["planted"]) for c in cases) == 8
    for c in cases:
        for claim in c["planted"]:
            assert claim in c["reply"], f"{c['id']}: the planted claim must appear in the reply"


def outcome(**over):
    base = {"route": "auto", "intent": "new_business", "language": "english", "services": ["seo"],
            "budget_pkr": 80000, "fixed": False, "seconds": 4.2, "cost_usd": 0.0001}
    return {**base, **over}


def test_score_lead():
    case = {"id": "x", "language": "english", "intent": ["new_business"], "services": ["seo"], "budget_pkr": 80000}
    row = score_lead(case, outcome())
    assert row["intent_ok"] and row["language_ok"] and row["services_ok"] and row["budget_ok"] and not row["unsafe"]
    row = score_lead({**case, "must_review": True}, outcome(budget_pkr=None, services=[]))
    assert row["unsafe"] and not row["budget_ok"] and not row["services_ok"]
    row = score_lead({**case, "services": []}, outcome(services=["seo"]))
    assert row["services_ok"] is False  # expecting no services means none may be invented


def test_summary_and_report():
    leads = [score_lead({"id": "a", "language": "english", "intent": ["new_business"]}, outcome()),
             score_lead({"id": "b", "language": "urdu", "intent": ["new_business"], "must_review": True},
                        outcome(language="urdu", route="review", fixed=True))]
    checks = [score_checker({"id": "c", "language": "english", "planted": ["x"]}, True, ["x"]),
              score_checker({"id": "d", "language": "english", "planted": []}, True, ["y"])]
    s = summarize(leads, checks)
    assert s["overall"]["unsafe_sends"] == 0 and s["overall"]["fixed_automatically"] == 1
    assert s["languages"]["english"]["checker_catch"] == 1.0 and s["languages"]["english"]["checker_false_alarm"] == 1.0
    assert s["languages"]["english"]["auto_sent"] == 1.0 and s["languages"]["urdu"]["auto_sent"] is None
    text = report(s, "test-model")
    assert "| Detected the language |" in text and "Sent alone when it should have asked" in text


def test_spam_language_not_scored():
    row = score_lead({"id": "s", "language": "english", "intent": ["spam"]}, outcome(intent="spam", language="other", route="spam"))
    assert row["language_ok"] is None and row["intent_ok"] is True
