"""Sample conversations for the public demo, so a visitor sees a lived-in app, not an empty one.

Each conversation goes through the real Lead Handler (the real steps, rules, fact check,
automatic fix, translation and approvals); only the AI's answers are pre-written, so seeding
costs nothing and works without a Groq key. Timestamps are spread over the last week.

    DEMO_SEED=true          fills an empty database on start (the Render demo does this)
    python -m scripts.seed_demo [--reset]   by hand
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.config import get_settings
from app.engine import executor
from app.llm.client import LLMClient
from app.models import Approval, InboundMessage, Lead, Run, RunStep

SITE = "Most clients spend Rs 150,000 to Rs 400,000 a month"


class _Scripted:
    """Stands in for the Groq SDK: plays back pre-written answers with realistic token counts."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[]))

    def _create(self, **kwargs):
        if not self.answers:
            raise RuntimeError("demo script ran out of answers")
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(item) if isinstance(item, dict) else item))],
            usage=SimpleNamespace(prompt_tokens=random.randint(700, 1500), completion_tokens=random.randint(60, 260)),
        )


class _Status(Exception):
    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.status_code = code


def _classify(intent="new_business", language="english", unoffered=False, asks_price=True):
    return {"intent": intent, "language": language, "search_query": "marketing services price",
            "asks_price": asks_price, "wants_unoffered_service": unoffered, "confidence": 0.96}


def _qualify(services, budget=None, urgency="normal", business=None, call=False, timeline=None):
    return {"services": services, "business_type": business, "monthly_budget_pkr": budget, "timeline": timeline,
            "urgency": urgency, "wants_call": call}


def _draft(reply):
    return {"reply": reply, "used_passage_ids": ["faq-0", "services-overview"]}


def _judge(*facts, bad=(), ok_language=True):
    claims = [{"text": f, "kind": "fact_about_flowpath", "supported": True} for f in facts]
    claims += [{"text": b, "kind": "commitment", "supported": False} for b in bad]
    claims.append({"text": "Would a 15-minute call work?", "kind": "courtesy", "supported": True})
    return {"claims": claims, "language_matches": ok_language}


# (who wrote, AI answers in order, how many days ago, then what the owner did, if anything)
CONVERSATIONS = [
    ({"channel": "email", "contact": "ayesha@koelbeauty.pk", "name": "Ayesha", "subject": "Instagram + Meta ads",
      "message": "Hi, we run a skincare brand online and want Instagram and Meta ads. Budget around Rs 300,000 a month, "
                 "we'd like to start within two weeks. Can we get on a call?"},
     [_classify(), _qualify(["social-media", "paid-advertising"], 300000, "high", "skincare brand", True, "within two weeks"),
      _draft("Hi Ayesha,\n\nThanks for reaching out! For a skincare brand like yours, our social media and paid advertising "
             "services cover 12–20 posts a month, short videos, Meta campaigns and weekly budget reviews. Most clients spend "
             "between Rs 150,000 and Rs 400,000 a month with us, plus their ad budget, and we confirm a fixed fee after a "
             "two-week audit.\n\nWould a 15-minute call this week work?\n\nTeam flowpath"),
      _judge(SITE, "Social media: 12–20 posts a month and short videos")], 0.05, None),
    ({"channel": "email", "contact": "bilal@lakeviewsociety.pk", "name": "Bilal",
      "message": "Hello, hamari housing society ke liye Google pe ranking chahiye, budget 1.5 lakh monthly hai, urgent nahi hai"},
     [_classify(language="roman_urdu"), _qualify(["seo"], 150000, "low", "housing society"),
      _draft("Bilal bhai, housing society ke liye hum Search aur SEO karte hain: technical audit, har mahine 4 naye pages aur "
             "Google Business updates. SEO ke results 3 se 6 mahine mein aate hain. Aapka budget 1.5 lakh bilkul theek hai! Team flowpath"),
      _judge("Search aur SEO: technical audit, 4 naye pages har mahine", bad=["Aapka budget 1.5 lakh bilkul theek hai"]),
      _draft("Bilal bhai, housing society ke liye hum Search aur SEO karte hain: technical audit, har mahine 4 naye pages aur "
             "Google Business updates. SEO ke results 3 se 6 mahine mein aate hain. Audit ke baad scope aur fee confirm hoti hai. "
             "15 minute ki call kar lein? Team flowpath"),
      _judge("Search aur SEO: technical audit, 4 naye pages har mahine", "Audit ke baad scope aur fee confirm hoti hai")], 0.2, None),
    ({"channel": "web_chat", "contact": "chat-visitor-1", "name": "Usman",
      "message": "Assalam o alaikum, aap log social media aur ads ka kitna charge karte hain? Mera restaurant hai DHA mein"},
     [_classify(language="roman_urdu"), _qualify(["social-media", "paid-advertising"], None, "normal", "restaurant"),
      _draft("Wa alaikum assalam Usman bhai! Humari social media aur paid ads ki monthly fee aam tor par Rs 150,000 se Rs 400,000 "
             "ke darmiyan hoti hai, plus ad budget. Audit ke baad fixed fee confirm hoti hai. 15 minute ki call schedule kar lein? Team flowpath"),
      _judge(SITE)], 0.4, None),
    ({"channel": "web_form", "contact": "sana@libasbysana.pk", "name": "Sana",
      "message": "السلام علیکم، مجھے اپنے کپڑوں کے برانڈ کے لیے انسٹاگرام مارکیٹنگ چاہیے۔ آپ کی فیس کیا ہے؟"},
     [_classify(language="urdu"), _qualify(["social-media"], None, "normal", "clothing brand"),
      _draft("وعلیکم السلام سنا! ہم آپ کے کپڑوں کے برانڈ کے لیے ماہانہ 12 سے 20 پوسٹس اور مختصر ویڈیوز بناتے ہیں۔ فیس آڈٹ کے بعد طے ہوتی ہے۔ "
             "کیا ہم 15 منٹ کی کال کر سکتے ہیں؟ Team flowpath"),
      _judge("12 سے 20 پوسٹس ماہانہ"),
      {"message_en": "Hello, I need Instagram marketing for my clothing brand. What is your fee?",
       "reply_en": "Hello Sana! We make 12 to 20 posts and short videos a month for your clothing brand. The fee is set after "
                   "the audit. Can we have a 15-minute call? Team flowpath"}], 0.6, None),
    ({"channel": "email", "contact": "khalid@oudhouse.ae", "name": "Khalid",
      "message": "مرحبا، نحن متجر عطور في دبي ونرغب في إعلانات على تيك توك وإنستغرام. هل تعملون مع عملاء خارج باكستان؟"},
     [_classify(language="arabic"), _qualify(["paid-advertising"], None, "normal", "perfume shop"),
      _draft("مرحباً خالد، نعم، نعمل مع عملاء حول العالم من لاهور. نقدم إعلانات ميتا وتيك توك مع مراجعات أسبوعية للميزانية. "
             "هل يناسبك اتصال لمدة 15 دقيقة؟ Team flowpath"),
      _judge("Meta and TikTok ads with weekly budget reviews"),
      {"message_en": "Hello, we are a perfume store in Dubai and want TikTok and Instagram ads. Do you work with clients "
                     "outside Pakistan?",
       "reply_en": "Hello Khalid, yes, we work with clients around the world from Lahore. We offer Meta and TikTok ads with "
                   "weekly budget reviews. Would a 15-minute call suit you? Team flowpath"}], 1.1, None),
    ({"channel": "web_form", "contact": "fahad@fitzone.pk", "name": "Fahad", "message": "Can you build a mobile app for our gym?"},
     [_classify(unoffered=True, asks_price=False), _qualify([], None, "low", "gym"),
      _draft("Hi Fahad, thanks for asking! flowpath focuses on three services: social media, paid advertising and search/SEO, "
             "so we don't build apps. If growing your gym's members online helps, we'd be happy to talk. Team flowpath"),
      _judge("flowpath offers social media, paid advertising and search/SEO")], 0.8, None),
    ({"channel": "email", "contact": "mehreen@chaiwala.pk", "name": "Mehreen",
      "message": "Our Meta ads stopped running since yesterday, please check urgently"},
     [_classify(intent="existing_client", asks_price=False),
      _draft("Hi Mehreen, thanks for letting us know. A team member will look into your Meta campaigns and get back to you. Team flowpath"),
      _judge()], 1.6, ("approve", None)),
    ({"channel": "email", "contact": "zara@tandoor.pk", "name": "Zara",
      "message": "We need SEO for 3 restaurant branches, budget 5 lakh a month. Can you guarantee first page on Google?"},
     [_classify(), _qualify(["seo"], 500000, "normal", "restaurant chain"),
      _draft("Hi Zara, thanks for reaching out. For three branches we'd run local SEO for each location. We guarantee first-page "
             "rankings within 3 months. Shall we book a call? Team flowpath"),
      _judge("Local SEO for each branch", bad=["We guarantee first-page rankings within 3 months"]),
      _draft("Hi Zara, thanks for reaching out. For three branches we'd run local SEO for each location. We guarantee strong "
             "results within 3 months. Shall we book a call? Team flowpath"),
      _judge("Local SEO for each branch", bad=["We guarantee strong results within 3 months"])], 2.3,
     ("edit", "Hi Zara, thanks for reaching out. For three branches we'd run local SEO for each location: Google Business "
              "profiles, location pages and reviews. Nobody can honestly guarantee rankings, but our audit will show what's "
              "realistic for your area. Shall we book a 15-minute call? Team flowpath")),
    ({"channel": "web_form", "contact": "omar@sabzhomes.pk", "name": "Omar",
      "message": "Need Google ads and landing pages for a housing project, budget around 6 lakh monthly, start next month"},
     [_classify(), _qualify(["paid-advertising", "seo"], 600000, "normal", "housing developer", False, "next month"),
      _draft("Hi Omar, thanks for getting in touch. For housing projects we run Google Search campaigns and landing pages per "
             "plot size. Most clients spend Rs 150,000 to Rs 400,000 a month with us plus ad budget; the fixed fee follows a "
             "two-week audit. Shall we book a 15-minute call? Team flowpath"),
      _judge(SITE, "Google Search campaigns and landing pages")], 3.2, None),
    ({"channel": "web_chat", "contact": "chat-visitor-4", "name": "Hamza",
      "message": "Kya aap ke paas video editor ki job hai? Main 2 saal se Reels edit kar raha hoon"},
     [_classify(intent="job_applicant", language="roman_urdu", asks_price=False),
      _draft("Shukriya Hamza! Hum Video editor (full time, Lahore ya remote) hire kar rahe hain. Apni CV aur kaam ke samples "
             "hello@flowpath.example par bhej dein. Team flowpath"),
      _judge("Hiring a video editor, full time, Lahore or remote")], 3.9, None),
    ({"channel": "web_form", "contact": "nida@bloomcafe.pk", "name": "Nida",
      "message": "Hi! We opened a cafe in Johar Town and need Instagram content. Budget is about 1 lakh a month."},
     [_classify(), _qualify(["social-media"], 100000, "normal", "cafe"),
      _draft("Hi Nida, congratulations on the new cafe! Our social media service covers 12–20 posts a month and short videos. "
             "Most clients spend Rs 150,000 to Rs 400,000 a month with us; the audit will show what fits your budget. Would a "
             "15-minute call work? Team flowpath"),
      _judge(SITE, "12–20 posts a month and short videos")], 4.6, None),
    ({"channel": "email", "contact": "raza@autoparts.pk", "name": "Raza", "message": "Do you run Google ads for car parts shops?"},
     [_classify(intent="general_question"), _qualify(["paid-advertising"], None, "low", "car parts shop"),
      _draft("Hi Raza, yes: our paid advertising service includes Google Search campaigns, which work well for shops people "
             "search for by part name. Happy to share how we'd set it up on a 15-minute call. Team flowpath"),
      _judge("Paid advertising includes Google Search campaigns")], 5.5, None),
    ({"channel": "web_form", "contact": "winner@prize.example",
      "message": "Congratulations! You have won a free iPhone 17, click bit.ly/claim-now"},
     [_classify(intent="spam", asks_price=False)], 2.8, None),
]

# typical time each step takes, so the heatmap looks like real traffic
STEP_MS = {"intake": (8, 25), "classify": (340, 560), "retrieve": (40, 120), "qualify": (420, 680), "draft": (900, 1600),
           "score": (520, 950), "revise": (1100, 1800), "translate": (450, 850), "send": (150, 420), "save_lead": (8, 30)}


def seed_demo(db_factory, reset: bool = False) -> int:
    """Add the sample conversations. Returns how many were added (0 if the database already has leads)."""
    with db_factory() as db:
        if reset:
            for model in (RunStep, Approval, Lead, InboundMessage, Run):  # children before parents
                db.query(model).delete()
            db.commit()
        elif db.query(Lead).first() is not None:
            return 0

    random.seed(7)
    settings = get_settings().model_copy(update={"send_mode": "dry_run"})  # samples are never emailed
    now = datetime.now(timezone.utc)
    added = 0
    for payload, answers, days_ago, decision in CONVERSATIONS:
        with db_factory() as db:
            run_id = executor.create_run(db, "lead_handler", payload).id
        executor.execute_run(run_id, llm=LLMClient(settings, sdk=_Scripted(answers)))
        if decision:
            _decide(db_factory, run_id, *decision, settings=settings)
        _backdate(db_factory, run_id, now - timedelta(days=days_ago))
        added += 1
    return added


def _decide(db_factory, run_id, action: str, reply: str | None, settings) -> None:
    """Record the owner's decision and resume the run directly (no queue, so no worker races the seed)."""
    from app.automations.lead_handler import edit_similarity
    from app.models import ApprovalStatus

    with db_factory() as db:
        approval = db.query(Approval).filter_by(run_id=run_id).one()
        draft = approval.payload.get("reply", "")
        final = reply if action == "edit" else draft
        approval.status = ApprovalStatus.edited if action == "edit" else ApprovalStatus.approved
        approval.final_payload = {"reply": final, "similarity": edit_similarity(draft, final), "note": None}
        approval.decided_at = datetime.now(timezone.utc)
        db.commit()
        approval_id = approval.id
    executor.resume_run(run_id, approval_id, llm=LLMClient(settings, sdk=_Scripted([])))


def _backdate(db_factory, run_id, when: datetime) -> None:
    with db_factory() as db:
        run: Run = db.get(Run, run_id)
        run.created_at = run.started_at = when
        t = when
        for step in run.steps:
            lo, hi = STEP_MS.get(step.node_id, (10, 30))
            if step.status.value != "waiting":
                step.duration_ms = random.randint(lo, hi)
            step.started_at = t
            if step.node_id == "approval" and step.status.value != "waiting":
                step.duration_ms = random.randint(4, 40) * 60_000  # a person took a while to answer
            t = t + timedelta(milliseconds=step.duration_ms)
            if step.status.value != "waiting":
                step.finished_at = t
        if run.finished_at:
            run.finished_at = t
        for lead in db.query(Lead).filter_by(run_id=run_id):
            lead.created_at = lead.updated_at = when
        for approval in db.query(Approval).filter_by(run_id=run_id):
            approval.created_at = when + timedelta(seconds=5)
            if approval.decided_at:
                approval.decided_at = when + timedelta(minutes=random.randint(5, 40))
        db.commit()


def seed_if_empty(session_factory) -> None:
    if get_settings().demo_seed:
        added = seed_demo(session_factory)
        if added:
            import logging
            logging.getLogger("autohub.demo").info("added %d sample conversations", added)
