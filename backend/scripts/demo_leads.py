"""Send sample leads in all four languages to a running AutoHub, then show what happened.

    docker compose exec api python scripts/demo_leads.py
    (or from your machine: python backend/scripts/demo_leads.py --url http://localhost:8000)

On Groq's free plan (8,000 tokens a minute on gpt-oss-20b) leads are sent 15 seconds
apart; use --delay 0 on a paid plan. Use --only 3 to send just one lead, and
--retry-failed to re-run any lead runs that failed (e.g. after a rate limit).
"""
import argparse
import os
import time

import httpx

LEADS = [
    ("English, hot lead", {
        "channel": "web_form", "contact": "ayesha@example.com", "name": "Ayesha",
        "message": "Hi, we run a skincare brand online and want to grow Instagram and run Meta ads. Budget is around "
                   "Rs 300,000 a month and we'd like to start within two weeks. Can we get on a call?"}),
    ("Roman Urdu, price question", {
        "channel": "web_chat", "contact": "chat-visitor-1", "name": "Usman",
        "message": "Assalam o alaikum, aap log social media aur ads ka kitna charge karte hain? Mera restaurant hai "
                   "DHA mein"}),
    ("Mixed English / Roman Urdu", {
        "channel": "email", "contact": "bilal@example.com", "name": "Bilal",
        "message": "Hello, hamari housing society ke liye Google pe ranking chahiye, budget 1.5 lakh monthly hai, "
                   "urgent nahi hai"}),
    ("Urdu script", {
        "channel": "web_form", "contact": "sana@example.com", "name": "Sana",
        "message": "السلام علیکم، مجھے اپنے کپڑوں کے برانڈ کے لیے انسٹاگرام مارکیٹنگ چاہیے۔ آپ کی فیس کیا ہے؟"}),
    ("Arabic, client abroad", {
        "channel": "web_form", "contact": "khalid@example.com", "name": "Khalid",
        "message": "مرحبا، نحن متجر عطور في دبي ونرغب في إعلانات على تيك توك وإنستغرام. هل تعملون مع عملاء خارج "
                   "باكستان؟"}),
    ("Job applicant (Roman Urdu)", {
        "channel": "web_chat", "contact": "chat-visitor-4", "name": "Hamza",
        "message": "Kya aap ke paas video editor ki job hai? Main 2 saal se Reels edit kar raha hoon"}),
    ("Service flowpath doesn't offer", {
        "channel": "web_form", "contact": "fahad@example.com", "name": "Fahad",
        "message": "Can you build a mobile app for our gym?"}),
    ("Existing client, urgent", {
        "channel": "email", "contact": "mehreen@example.com", "name": "Mehreen",
        "message": "Our Meta ads stopped running since yesterday, please check urgently"}),
    ("Spam", {
        "channel": "web_form", "contact": "winner@example.com",
        "message": "Congratulations! You have won a free iPhone 17, click bit.ly/claim-now to get it"}),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("AUTOHUB_URL", "http://localhost:8000"))
    parser.add_argument("--only", type=int, help="send just lead number N (1-based)")
    parser.add_argument("--delay", type=float, default=15, help="seconds between leads (free plan: keep ~15)")
    parser.add_argument("--retry-failed", action="store_true", help="re-run failed Lead Handler runs instead")
    args = parser.parse_args()

    if args.retry_failed:
        with httpx.Client(base_url=args.url, timeout=30) as client:
            failed = client.get("/api/runs", params={"automation": "lead_handler", "status": "failed"}).json()
            for run in failed:
                client.post(f"/api/runs/{run['id']}/retry").raise_for_status()
                print(f"retrying {run['id']}")
                time.sleep(args.delay)
            print(f"{len(failed)} run(s) re-queued" if failed else "no failed runs")
        return

    headers = {"X-AutoHub-Key": os.environ["INBOUND_API_KEY"]} if os.environ.get("INBOUND_API_KEY") else {}
    chosen = [LEADS[args.only - 1]] if args.only else LEADS

    with httpx.Client(base_url=args.url, timeout=30) as client:
        sent = []
        for i, (label, lead) in enumerate(chosen):
            if i and args.delay:
                time.sleep(args.delay)
            resp = client.post("/api/leads/inbound", json=lead, headers=headers)
            resp.raise_for_status()
            sent.append((label, resp.json()["run_id"]))
            print(f"sent  {label}", flush=True)

        print("\nwaiting for the worker...")
        deadline = time.time() + 180
        pending = dict(sent)
        results = {}
        while pending and time.time() < deadline:
            for label, run_id in list(pending.items()):
                run = client.get(f"/api/runs/{run_id}").json()
                if run["status"] not in {"queued", "running"}:
                    results[label] = run
                    del pending[label]
            time.sleep(1.5)

        print(f"\n{'lead':34} {'outcome':18} {'tokens':>7} {'cost $':>9}")
        for label, run_id in sent:
            run = results.get(label)
            if run is None:
                print(f"{label:34} still running")
                continue
            route = (run.get("output") or {}).get("route")
            if run["status"] == "failed":
                outcome = "FAILED"
            elif run["status"] == "waiting_approval":
                outcome = "-> needs review"
            else:
                outcome = {"auto": "auto-sent", "spam": "spam, ignored"}.get(route, run["status"])
            print(f"{label:34} {outcome:18} {run['total_tokens']:>7} {run['total_cost_usd']:>9.5f}")
            if run["status"] == "failed":
                print(f"    error: {run['error'][:160]}")

        if any(r["status"] == "failed" for r in results.values()):
            print("\nsome runs failed; re-run them with:  python scripts/demo_leads.py --retry-failed")

        batch = {run_id for _, run_id in sent}
        approvals = [a for a in client.get("/api/approvals").json() if a["run_id"] in batch]
        if approvals:
            print("\nwhy these need a person:")
            for a in approvals:
                print(f"  - {a['payload'].get('name') or a['payload']['contact']}: {a['reason']}")


if __name__ == "__main__":
    main()
