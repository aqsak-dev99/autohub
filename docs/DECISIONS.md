# AutoHub — Design Decisions

A running log of the choices behind AutoHub: what was decided, why, and what it costs. Each entry is short on purpose.

---

## 1. Build an automation hub, not another standalone agent
**Decision:** One hub that runs several AI automations, instead of a single new agent.
**Why:** My portfolio already has two agent projects (LeaseFlow: LangGraph multi-agent + RAG; MyFitness: Spring AI tool-calling). What was missing was *business automation*: triggers, integrations, human review, and workflows a company would actually run. A hub shows that, and it's what freelance clients pay for.
**Trade-off:** Broader scope. Contained by limiting it to three automations done well rather than many shallow ones.

## 2. Runs and steps are the core data model
**Decision:** Every execution is a `Run`; every unit of work inside it is a `RunStep` storing input, output, model, tokens, cost, duration, attempts and error.
**Why:** Observability is built in, not bolted on. The dashboard, the React Flow run replay, cost metrics and debugging all come from this one structure, for every automation, with no per-automation code.
**Trade-off:** More database writes per run (one commit per step). Acceptable at this scale, and it's what makes "running" status visible live.

## 3. Automations write steps with a context manager
**Decision:** Automation code wraps work in `with ctx.step("node_id") as s:`; the engine records timing, status, errors and LLM usage automatically.
**Why:** Automation code stays about business logic. Tracing can't be forgotten, and a failure is always recorded on the exact step that failed.
**Trade-off:** Step ids must match node ids in the automation's graph. Guarded by a test that checks every graph edge points at a real node.

## 4. Hand-written agent loop instead of LangGraph
**Decision:** Plain Python orchestration on top of my own LLM client.
**Why:** LeaseFlow already demonstrates LangGraph. Writing the loop myself shows the fundamentals frameworks hide: retries, structured output, state, tracing. It also keeps dependencies small and every step explainable in an interview.
**Trade-off:** No built-in graph checkpointing; pausing for humans is handled explicitly (decision 10).

## 5. Groq, with `openai/gpt-oss-20b` as the default text model
**Decision:** Groq for inference; `gpt-oss-20b` for text, set in config. (A Qwen vision model was configured for the Document Extractor until it was dropped, decision 60.)
**Why:** Groq is fast and OpenAI-compatible, which keeps the client simple. The original plan was Llama 3.3 70B, but Groq moved it to enterprise-only pricing during the build, so a self-serve key can't use it. `gpt-oss-20b` is available, cheap ($0.075 / $0.30 per 1M tokens) and supports JSON mode. Reasoning effort is set to `low` to keep latency down.
**Trade-off:** Provider model lineups change. Handled by keeping model ids in config and by decision 9.

## 6. Retry only transient errors, in one place
**Decision:** `tenacity` retries 429, 5xx, timeouts and connection errors with exponential backoff and jitter. A 400 fails immediately. The Groq SDK's own retries are disabled (`max_retries=0`).
**Why:** Retrying a bad request just wastes money; it's a bug. Owning retries in one layer means attempts are counted accurately and stored per step, so rate-limit pressure is visible.
**Trade-off:** A long outage still fails the run after the configured attempts, which is the correct outcome.

## 7. Structured output with self-repair
**Decision:** `complete_json` asks for JSON, validates it against a Pydantic schema, and on failure sends the validation errors back once so the model can fix its own output.
**Why:** Automations branch on model output (intent, confidence, extracted totals). Unvalidated JSON is the most common way LLM pipelines break. One repair round fixes most mistakes cheaply; all attempts' tokens are billed to the step, so the cost of repairs is visible.
**Trade-off:** The schema in the prompt adds input tokens (~140 in the system check). Worth it for guaranteed structure.

## 8. Redis queue with a graceful fallback
**Decision:** The API creates the run and returns `202` with its id immediately; an RQ worker executes it. If Redis is unreachable, the run executes as a FastAPI background task instead.
**Why:** LLM calls take seconds, and webhook senders (Twilio, n8n) time out quickly. The fallback means the hub degrades instead of losing work.
**Trade-off:** The worker doesn't hot-reload; after changing automation code, `docker compose restart worker`.

## 9. Verify models before using them
**Decision:** A System Check automation lists the account's available models and fails at its first step if a configured model is missing, then tests a plain completion and a structured completion.
**Why:** Decision 5 showed models get retired or gated. One run after setup or deploy proves the key, models, queue, worker, retries and JSON parsing all work.

## 10. Human-in-the-loop as a run state
**Decision:** An automation raises `NeedsApproval`; the engine saves an `Approval` and sets the run to `waiting_approval` rather than finishing it.
**Why:** For customer-facing replies, a wrong answer costs more than a slow one. Making approval a first-class state means the dashboard can show a queue, and the approve/edit/reject decision is recorded next to what the AI proposed.

## 11. Idempotent execution
**Decision:** A run only executes when its status is `queued`.
**Why:** Queues can deliver a job twice. Without this guard a customer could get the same WhatsApp reply twice.

## 12. Workflow graphs stored on the automation, in React Flow's format
**Decision:** Each automation's `{nodes, edges}` lives in the database, shaped exactly as React Flow expects.
**Why:** The backend owns the workflow shape, so the dashboard never hardcodes it, and a run's steps map directly onto nodes for live replay.
**Trade-off:** React Flow is used as a read-only map and run viewer, not a drag-and-drop builder. n8n already provides visual building; a builder would cost days for little portfolio value.

## 13. n8n for scheduling and channel glue, Python for intelligence
**Decision:** n8n handles schedules and the WhatsApp channel connection; the AI logic lives in the Python API.
**Why:** Each tool does what it's best at. n8n workflows are quick to change and show integration skills; Python keeps the agent logic testable and versioned. Workflow JSON is committed to the repo.
**Trade-off:** Two systems to run. Docker Compose starts both with one command.

## 14. Twilio WhatsApp sandbox instead of Meta's API *(superseded by 53)*
**Decision:** Twilio's sandbox for the demo.
**Why:** Meta's WhatsApp Business API requires business verification, which can take days. The sandbox works in minutes, and the integration code is nearly identical, so switching later is a config change.

## 15. Keyword search (BM25) now, embeddings only if evals show they're needed
**Decision:** The Lead Handler searches flowpath's content with BM25, ported from flowpath's own assistant. Embeddings (`fastembed` + pgvector) were planned but are deferred.
**Why:** The knowledge base is ~17 short passages. At that size keyword search is accurate, free and instant, and flowpath's assistant passed its 29-case eval set using it. The real retrieval problem is language: customers write in Roman Urdu, Urdu and Arabic, while the content is English. That's solved by decision 20, not by a vector database. Phase 6 evals will measure whether embeddings find passages BM25 misses; they get added only if the numbers say so.
**Trade-off:** Weaker on paraphrases with no shared words. Covered for now by a synonym list and the query rewrite.

## 16. Small, deliberate infrastructure choices
- **Enums stored as strings:** readable rows and no Postgres enum migrations when a status is added.
- **Health check per dependency:** Redis down reports "degraded", not "down", because the API still works.
- **n8n pinned to a version:** `latest` could change behaviour mid-project.
- **Settings validated by Pydantic:** a bad config value fails at startup, not mid-request.

## 17. Development environment: GitHub Codespaces
**Decision:** Develop in a codespace (connected from desktop VS Code) instead of running Docker locally.
**Why:** My laptop couldn't run Docker Compose reliably. A devcontainer config makes the environment reproducible: anyone can open the repo and get the same Python, Node and Docker setup in minutes.
**Trade-off:** Limited free hours. Managed by stopping the codespace after each session.

## 18. Tests use a fake Groq SDK
**Decision:** Tests inject a scripted fake SDK and run on SQLite.
**Why:** No API key, network or Docker needed, so they run in CI. The fake can replay exact scenarios: rate limits followed by success, invalid JSON followed by a repair, a missing model.

## 19. The LLM extracts facts; code makes the decisions
**Decision:** The qualify step asks the model only for facts (services, budget, urgency, business type). The lead score, temperature and auto-send vs review are computed by plain Python in `lead_rules.py`.
**Why:** Decisions are then explainable ("+20 budget Rs 150,000 to 400,000 a month"), testable without an LLM, and identical for identical facts. An LLM asked for "a lead score" gives different numbers for the same lead.

## 20. Rewrite the query into English instead of multilingual search
**Decision:** The classify step returns an English `search_query` alongside the intent and language, and retrieval searches with that.
**Why:** One extra field in a call that already happens, versus a multilingual embedding model. The content stays in one language and is never duplicated.

## 21. Leads are scored on flowpath's own budget bands
**Decision:** Budgets are mapped to the four bands flowpath's contact form already uses.
**Why:** Scores mean something to the business, and website-form and WhatsApp leads land on the same scale.

## 22. A separate judge call checks the draft
**Decision:** After drafting, a second LLM call checks that every claim is supported by the retrieved passages and that the language matches, and returns a confidence.
**Why:** A model grading its own output in the same call tends to approve it. A separate, strict prompt with the passages in front of it catches unsupported claims before a customer sees them.
**Trade-off:** One more call per lead (~400 tokens). Worth it for customer-facing text.

## 23. A deterministic price guard
**Decision:** Code finds every money amount in the draft (Rs 150,000, 1.5 lakh, 50k, Urdu and Arabic digits) and sends the reply to review if any amount isn't in the knowledge base.
**Why:** An invented price is the most damaging mistake a sales reply can make, so it's checked by rule rather than trusted to the judge.

## 24. Language-aware review policy
**Decision:** Urdu-script and Arabic replies always go to review (`REVIEW_LANGUAGES`); unsupported languages get an English reply that is reviewed.
**Why:** The models are strongest in English. Those languages stay supervised until Phase 6 evals measure per-language accuracy; then the setting can change with evidence behind it.

## 25. Stronger model only for the customer-facing draft
**Decision:** `gpt-oss-120b` writes the reply; `gpt-oss-20b` does classification, extraction and judging.
**Why:** Reply quality, especially in Roman Urdu and Arabic, is what the customer sees. The structured steps produce short JSON where the small model is accurate and costs half as much.

## 26. Approval is a pause, not an end
**Decision:** A reviewed run stays `waiting_approval`; the approval step is marked `waiting`. Approve, edit or reject resumes the same run, which then sends (or not) and saves the lead. A second decision returns 409.
**Why:** One run tells the whole story of a lead on the graph, including how long the human took. The 409 stops a double-click from sending a reply twice. Edits store a similarity score against the draft, which becomes the edit-rate metric.

## 27. Dry-run sending until real channels are wired
**Decision:** The send step records "would send" in Phase 2; Twilio delivery plugs into the same function in Phase 4.
**Why:** The whole pipeline can be built and tested safely without messaging real people.

## 28. Spam short-circuits
**Decision:** Messages classified as spam with confidence ≥ 0.8 skip straight to saving the lead.
**Why:** No tokens spent drafting replies to scams, and nothing is ever sent to them.

## 29. Patient retries for rate limits, plus manual retry
**Decision:** A 429 gets up to 6 attempts (vs 3 for other transient errors) and never retries sooner than the provider's `Retry-After` hint. Failed runs mark their lead `failed` and can be re-run with `POST /api/runs/{id}/retry`, which reuses the same run and lead.
**Why:** Found in the first real run: 9 leads sent at once exceeded Groq's free-plan limit (8,000 tokens/minute), and three quick retries over ~3 seconds weren't enough when the window needed up to a minute. Two leads failed and were left looking "new". Now they wait, and if they still fail, the dashboard shows it and they can be retried without creating a duplicate lead.

## 30. Repeating the customer is fine; promising is not
**Decision:** The judge treats restating the customer's own details ("you mentioned a Rs 300,000 budget") as needing no support, but treats agreeing to them ("we can start within two weeks", "your budget is fine") as a claim that must be supported. The draft prompt forbids those promises; the price guard allows amounts the customer gave.
**Why:** Also from the first real run. Drafts said "we can start within two weeks" and "aapka budget bilkul theek hai". The judge was right to stop them, since nothing in flowpath's content supports a start date before the audit, but it also flagged harmless restatements. Separating the two keeps the safety net while letting good replies auto-send.

## 31. Pin the passages the prompt depends on
**Decision:** The services overview and the pricing/audit FAQ are always given to the draft and the judge, on top of the four passages the search returns.
**Why:** From the second real run. The draft prompt says "say which services flowpath offers" and "the fee is quoted after the audit", but those facts only reached the model when the search happened to return them. When they didn't, the judge correctly flagged true statements as unsupported (Bilal's "audit ke baad fee confirm hogi"), and in one case the model invented "web design" as a service. A prompt must never ask for a fact the model can't see. Pinned passages are marked in the retrieval step so the trace shows which were searched and which were pinned.

## 32. The judge labels claims; code computes confidence
**Decision:** The judge no longer returns a confidence score. It lists each claim in the reply and labels it `fact_about_flowpath`, `commitment`, `restates_customer` or `courtesy`, plus whether the passages support it. Code counts only facts and commitments: confidence = supported ÷ claims needing support, and any unsupported one sends the reply to review. The judge runs with medium reasoning effort; other steps stay on low.
**Why:** From the third real run. With a single overall score, the judge flagged things its own prompt said needed no support ("shall we book a 15-minute call?"), and the same reply could pass one run and fail the next: the job-applicant reply was auto-sent in run 2 and reviewed in run 3 for a call offer alone. Labelling is a narrower task the small model does consistently, and a mislabel on a courtesy can no longer block a reply. Same principle as decision 19: the LLM extracts, code decides.
**Trade-off:** The judge's output is larger (one entry per claim, ~1,200 tokens max) and medium reasoning adds latency to that step. The dashboard gains something in return: the inbox can show each claim with its label.

## 33. Reasoning tokens share the output budget
**Decision:** The judge gets 3,000 output tokens (was 1,200), and Groq's `json_validate_failed` 400 is treated as a repairable bad output, not a bad request: the call is retried once asking for a complete, shorter answer. Other 400s still fail immediately. The "how we work" passage is now pinned too, since drafts mention the audit.
**Why:** From the fourth real run. Raising the judge's reasoning effort (decision 32) made it think longer, and on these models reasoning tokens count against the same limit as the answer. On two long replies the JSON was cut off mid-way, Groq rejected it, and the runs failed. A small, fixable cause that looked like a crash; now it's one extra call at worst.

## 34. Phase 4 before Phase 3
**Decision:** WhatsApp (originally Phase 4) was built before the Document Extractor.
**Why:** The schedule slipped by three days. Real WhatsApp delivery turns the strongest feature, the Lead Handler, from a dry run into something that replies to a phone, while the extractor was the most standalone piece and the safest to slim down if time ran short.

## 35. Answer Twilio at once, reply later *(superseded by 53)*
**Decision:** The webhook checks the signature, records the message, queues a Lead Handler run and returns empty TwiML immediately. The reply is sent later by the worker through Twilio's REST API.
**Why:** Twilio gives a webhook 15 seconds; four LLM calls can take longer. Replying in the webhook response would make slow runs time out and get retried.

## 36. Verify Twilio's signature, behind a proxy *(superseded by 53)*
**Decision:** Every webhook must carry a valid `X-Twilio-Signature` (HMAC-SHA1 of the URL and parameters with the auth token), compared in constant time. The URL used is `PUBLIC_BASE_URL`, else the proxy's forwarded host, because behind Codespaces or Render the app sees an internal address, not the one Twilio signed. Without a token the webhook refuses to run (503) rather than accept unverified messages.
**Why:** A public webhook URL is easy to find. Without the check anyone could post fake customer messages and spend the AI budget, or make AutoHub message any number. The implementation was checked against the example in Twilio's documentation.

## 37. Claim the message id before doing anything
**Decision:** Each Twilio `MessageSid` is inserted into `inbound_messages` (unique) before a run is created; a second delivery fails that insert and is acknowledged without a run.
**Why:** Twilio retries webhooks, and a duplicate would mean a second lead and a second reply to the customer. Claiming first, instead of checking first, also holds when two deliveries arrive at the same instant.

## 38. Three locks on sending (still applies to email: SEND_MODE, credentials, EMAIL_SEND_ALLOWLIST)
**Decision:** A real WhatsApp message goes out only when `SEND_MODE=live`, Twilio credentials are set, and the number is on `LIVE_SEND_ALLOWLIST` (if one is set). Anything else is a recorded dry run with the reason. A Twilio error fails the step, so the run shows as failed and can be retried.
**Why:** A system that messages people should be hard to set off by accident: the demo script's made-up numbers and tests never reach a real phone. Plain `httpx` is used instead of the Twilio SDK, since two small HTTP calls don't justify a dependency and are easy to fake in tests.

## 39. Digest numbers come from code, not the model
**Decision:** The daily digest's counts, hot leads and costs are built by SQL and a template. The LLM writes one line on what to do first, and is told not to add numbers. If that call fails the digest goes out without the line; if WhatsApp delivery fails it's recorded on the run instead of failing it.
**Why:** A summary with a wrong number is worse than no summary. The parts that must be right are deterministic, and the part that can be wrong is optional. n8n owns the schedule and watches the outcome (it flags a failed run), which is the job it's best at.

## 40. Meta's Cloud API as the live provider, Twilio kept behind the same interface *(superseded by 53)*
**Decision:** `WHATSAPP_PROVIDER` picks Meta's WhatsApp Cloud API (default) or Twilio. Both share `send_reply`, the allowlist, the dry-run rules and the duplicate protection; each has its own webhook and signature check (Meta: HMAC-SHA256 of the raw body with the app secret, plus the verify-token handshake).
**Why:** Twilio's account verification rejected Pakistani phone numbers, by SMS and by voice call. Meta's API is WhatsApp's own, verifies test recipients through WhatsApp rather than SMS, and is what businesses in Pakistan use in production. Because sending and receiving were already isolated in one module, switching provider was a contained change rather than a rewrite. Meta's signature check was confirmed against a signature produced independently with `openssl`.

## 41. Small startup schema patches until Alembic
**Decision:** `init_db` runs a short list of idempotent `ALTER` statements after `create_all` on Postgres.
**Why:** Meta's message ids are longer than the 64 characters first allowed for Twilio's. `create_all` never alters an existing table, and resetting the database again would wipe test data. A patch list that's safe to run on every start fixes it now; Alembic replaces it before deployment.

## 42. Email as the always-on public channel
**Decision:** The Lead Handler also works over email: Gmail SMTP sends replies (threaded with `In-Reply-To` / `References` so they appear inside the customer's conversation), and an IMAP poll reads new enquiries. flowpath's contact-form leads get email replies.
**Why:** Meta's test number can only message five pre-registered numbers, so an interviewer couldn't try the WhatsApp demo themselves. Anyone can email an address. A Gmail app password also doesn't expire, while Meta's quick token lasts a day. WhatsApp stays in the project for the recorded demo; email is what stays live. Email is also realistic for an agency: website enquiries expect an email back.

## 43. Never answer a machine
**Decision:** The inbox poll skips mail from no-reply addresses and mail daemons, auto-replies (`Auto-Submitted`, `X-Autoreply`), bulk and list mail (`Precedence`, `List-Id`, `List-Unsubscribe`), and AutoHub's own address. Each skip is reported with its reason.
**Why:** The classic failure of email automation is two bots replying to each other until a quota runs out, or a bounce being "answered". These headers are the standard signals (RFC 3834 for auto-replies); checking them costs nothing.

## 44. Read safely: recent, unread, peeked, claimed
**Decision:** Only unread mail from the last day is searched (`EMAIL_POLL_SINCE_DAYS`), at most 20 per poll. Messages are fetched with `BODY.PEEK` and marked read only after they're handled; one that fails stays unread for the next poll. Each is claimed by a hash of its `Message-ID` before a run starts. Quoted history is stripped so the model sees only the new text.
**Why:** Connecting a mailbox must never reply to its old backlog. Peeking means a crash loses nothing, and the Message-ID claim means two overlapping polls (n8n's minute timer and a manual run) can't answer one email twice.

## 45. Polling, scheduled by n8n, instead of push
**Decision:** n8n calls `POST /api/email/poll` every minute; `scripts/poll_inbox.py` does the same by hand.
**Why:** Gmail push notifications need a Google Cloud project with Pub/Sub. For a demo, a one-minute delay is fine, and polling has no extra infrastructure. It also gives n8n a second real job alongside the daily digest: n8n owns the schedules, Python owns the logic.

---

## 46. The graph is the interface
The dashboard draws every automation from the graph the backend stores (decision 3), then paints that same graph three ways: a single run (which branch it took, per-step input and output), a heatmap of averages over the last 7 days (latency, cost or failure rate), and a live view while a run is in progress. One picture answers "what happened", "where does time and money go" and "what is it doing now", which is what an ops person actually asks.

## 47. Human wait time is kept off the heatmap
A reply waiting 22 minutes for approval would make the approval node the "slowest step" and hide the real bottleneck (the draft call). Human nodes are drawn dashed with their own average wait, and the hotspot only ranks machine steps.

## 48. Same-origin proxy instead of CORS
Vite forwards `/api` to the backend, in Docker and in Codespaces, so the browser only ever talks to one origin. No CORS rules to get wrong, and the same build works behind Render's single domain later.

## 49. Polling, not WebSockets, for live runs
A run page refetches every 1.2 s only while the run is queued or running, then stops. Runs last seconds, so this is indistinguishable from push for a viewer, and it needs no socket server, sticky sessions or reconnect logic.

## 50. Show the reviewer the evidence, not just the draft
The approvals screen shows why the reply was held (the rule that fired), each claim the checker extracted with its verdict, and the knowledge passages it was grounded in. A reviewer checks the risky sentence instead of re-reading everything, and edits are stored beside the AI draft so the edit rate measures AI quality over time.

## 51. No UI or chart library (still true after the redesign)
Plain CSS and one hand-written SVG bar chart. The pages are tables, panels and one graph; a component kit would add weight and make it look like every other template. Status colours also differ by line style (solid, dashed), not only hue.

## 52. Hot leads show one row per person
Someone who messages twice is one prospect; the overview lists their best-scoring lead once so the list isn't padded with repeats.

## 53. WhatsApp removed; email and the website form are the live channels
**Decision:** The WhatsApp channel (Meta Cloud API and Twilio, decisions 14, 35–40) was taken out of AutoHub. Customers now reach the Lead Handler by email (the inbox poll) and through a public contact form on flowpath's site (`POST /api/forms/contact`), and both get email replies. The WhatsApp code is kept in a separate archive for a later project.
**Why:** Meta locked the test account and requires business verification before any message is sent, and verification needs documents for a registered business, which a concept agency doesn't have. Keeping a channel that can never go live would add code, settings and tests that only say "pending". Email and the form can be tried by anyone, including an interviewer. Because every send already went through one `send_reply` function and every message through one intake (`app/intake.py`), the removal touched no AI logic; a new channel is another branch in `channels.py` plus an intake route.

## 54. A public form needs its own protections
**Decision:** The contact form is unauthenticated (a browser posts it), so it gets: an origin allowlist (`FORM_ALLOWED_ORIGINS`), a hidden honeypot field that bots fill in and people never see (answered with a fake success), a rate limit per email address (from the database) and per IP (in memory), and a fingerprint of address + message so a double-click starts one run. The server-to-server intake keeps its `X-AutoHub-Key`.
**Why:** Every form submission costs AI calls and sends an email. Without these, a bot could spend the Groq budget or use flowpath's address to email strangers. A CAPTCHA would add a third-party script and friction for real customers, which isn't worth it at this traffic.

## 55. Designed for the business owner; engineering behind one switch
**Decision:** The dashboard was redesigned around the person who would pay for it: plain language ("Asks you first", "Double-checks every fact"), rupees instead of dollars, a suggested next step on every conversation. A single **Technical details** switch adds the engineering view to every screen (models, tokens, latency, raw step data, run graphs, heatmaps) and reveals the run list and heatmap pages. The first version (decisions 46–51) looked like an engineer's monitoring console.
**Why:** An automation tool earns trust by being understandable to the owner, not by showing tokens. Keeping the depth one click away (rather than in a separate app) means the same screen answers "what happened with this customer?" and "why did that step take 1.2 s?", and makes the engineering easy to show without cluttering the product.

## 56. The live canvas is the home page
**Decision:** Home is a React Flow canvas of the Lead Handler in business terms, fed by `GET /api/stats/live`: customers being answered appear as avatars on the step they're at, edges into busy steps animate, and the "Asks you first" node carries the count of replies waiting. Engine steps are grouped into business steps (intake + classify = "Reads the message").
**Why:** It shows what the product does in one glance, which a table of runs never does, and it's the most memorable screen for a demo. Grouping keeps the owner's picture simple while the technical graph (decision 46) keeps every real step.

## 57. Rules belong to the owner, with a preview before saving
**Decision:** The routing switches (auto-send confidence, languages to review, prices not on the site, existing clients, unoffered services) are saved in the database (`app_settings`) and read on every run; environment variables are only the defaults. Three checks can't be switched off: unsupported claims, a reply in the wrong language, an unsupported customer language. `POST /api/rules/preview` replays the routing over the last 7 days from what each run recorded (classify and score outputs) and reports who would have been answered alone or sent to the owner.
**Why:** How cautious to be is a business decision, so the business should make it without a redeploy. The preview turns a scary setting into an informed one, and it's free and instant because routing is pure code over saved facts (decisions 19 and 32), not another model call. The locked checks are the failures nobody would notice until a customer did.

## 58. Fix unsupported claims automatically, once, then re-check
**Decision:** When the fact check finds a claim the knowledge base doesn't support, or the price guard finds an invented price, a `revise` step asks the draft model to remove exactly those statements (or replace them with "a team member will confirm this") and change nothing else. The fixed reply goes through the same judge and the same routing code again. One attempt only: if anything is still unsupported, or the fix call fails, the original reply goes to the owner with the reason. The run records both versions and what was removed.
**Why:** Most held replies were good replies with one overreaching sentence ("your budget is perfect!"). Sending all of them to a person wasted the owner's time; sending them as they were would put a promise in a customer's inbox. Removing the sentence and re-checking keeps the safety guarantee (nothing unsupported is ever auto-sent, because the second check uses the same rules) while more customers get an instant answer. A single attempt keeps cost and latency bounded and avoids a model arguing with itself.

## 59. Translate held replies for the owner
**Decision:** When a reply in Urdu, Roman Urdu or Arabic is held, a `translate` step adds a faithful English version of the customer's message and the draft to the approval, using the cheaper model. A failed translation doesn't block the approval. The dashboard notes when the owner has edited the draft after the translation was made.
**Why:** An owner can't responsibly approve something they can't read, and the review languages are exactly the ones an English-reading owner may not. Translating only held replies keeps the cost to the cases a person actually looks at.

## 60. One automation done well instead of three half-done *(partly superseded by 73 and 74)*
**Decision:** The Document Extractor (planned Phase 3) was removed from the registry, models, settings and docs before it was built; on startup, retired automations are deleted if they never ran, or hidden if they have history. The System Check now verifies the two models actually used.
**Why:** With the deadline close, a deployed, evaluated Lead Handler shows more than a second automation without evals. A listed automation that fails with "no implementation" would also make the hub look unfinished. The run engine stays general: adding an automation is still a new class plus a registry entry.

## 61. A self-refilling SQLite demo instead of a hosted database
**Decision:** The public demo is one free Render web service whose SQLite database sits on the service's own disk. Render wipes that disk on every restart or wake-up, and `DEMO_SEED` refills it with the sample conversations each time. Postgres (with the Redis worker) stays the setup for real use and local development.
**Why:** Render's free Postgres is deleted after 30 days, which would kill the demo in the middle of application season, and a paid database for a demo isn't justified. A demo that resets itself also never fills up with test messages or needs cleaning. The trade-off, visitors' Try-it conversations disappearing when the service sleeps, is fine for a demo.

## 62. Signed-cookie login with three roles
**Decision:** The owner logs in with `ADMIN_PASSWORD`; "Explore the demo" gives a viewer role with no password; n8n and scripts use the `X-AutoHub-Key` header. The session is an HMAC-signed cookie (role + expiry), HttpOnly and SameSite=Lax, so there's no session table. Viewers can see everything and use Try it, but can only approve replies to their own test messages and can't save rules. With no password set, login is off.
**Why:** The approval and rules endpoints change what customers receive, so a public URL needed a login before going live. A viewer role lets an interviewer use the product instead of looking at screenshots, without being able to change the sample data for the next visitor. A third-party auth service would be more moving parts than one owner needs.

## 63. Alembic, with existing databases adopted automatically
**Decision:** The schema is managed by Alembic migrations, run on every start. A database created earlier by `create_all` (with no `alembic_version` table) is stamped as the first migration once, after creating anything it's missing, then upgraded normally. A test fails if `models.py` and the migrations ever disagree.
**Why:** The startup patch list (decision 41) couldn't express real changes safely. Adopting old databases automatically means the codespace database (and its test data) keeps working without a manual step.

## 64. Limits on "Try it"
**Decision:** Test messages are limited per visitor (10 an hour, by IP) and in total (150 a day on the demo), with friendly messages when the limit is reached.
**Why:** Every test message is four or more real AI calls. Without a ceiling, one script or one enthusiastic visitor could use up the Groq free quota and break the demo for everyone else.

## 65. Evals measure safety per language, not just accuracy
**Decision:** The eval set is small and hand-labelled (40 messages, 10 per language, plus 16 fact-check replies with half planted), and runs through the real pipeline rather than testing prompts in isolation. Besides accuracy (intent, language, services, budget), it reports the fact checker's catch rate and false-alarm rate, and one hard number: replies sent on their own that the rules say a person must see. The report turns the numbers into a per-language recommendation for the Rules page.
**Why:** "Is the AI good?" isn't actionable; "is it safe to stop reviewing Urdu replies?" is, and that's the decision the review rules (decision 24) were waiting on. A misread language is the most dangerous failure (an Urdu message classified as English skips Urdu review), so it shows up as an unsafe send, not just a missed label. Forty labelled cases are enough to see a language that's clearly worse; more would mostly cost free-plan quota.

## 66. CI without secrets; evals by hand
**Decision:** CI runs the unit tests (with a scripted fake of the Groq SDK), the dashboard build, and builds and starts the production image. The evals call the real models, so they're a separate workflow started by hand with a repository secret.
**Why:** Tests must be fast, free and deterministic on every push; evals are slow, cost quota and vary run to run. Building the real image in CI catches a broken Dockerfile before Render does.

## 67. "Abyss": a dark theme with one source of light
**Decision:** The dashboard moved from a light theme to a deep sea-blue dark one (#021024 → #C7E5F2): glass cards over a dark background, an aurora of light at the top of Home that the cards float over, and a cyan glow used only where the AI is actually working (busy steps on the live canvas, the step running in a conversation, the selected node). Warm amber stays reserved for "this needs you". The login page is split: the form on one side, generated line art on the other.
**Why:** The light version read as a standard admin template. Dark with restrained glow gives the product a recognisable identity, and keeping the glow tied to live AI activity means it carries information rather than decoration. The line art is SVG generated in code, so the login page loads no images.

## 68. An opening animation that never gets in the way
**Decision:** A short splash plays over the app while it loads: glowing rings ripple out, a spark becomes the ✦ mark, and the name slides out. It plays once per browser session, waits for the app to be ready rather than covering it longer than needed, can be skipped with a click or any key, and becomes a plain fade for people who turn off motion in their system settings. It lasts about 1.7 s and is CSS and SVG only.
**Why:** It gives the demo a memorable first second and covers the free server's wake-up delay, but an animation that repeats on every page load or can't be skipped quickly becomes something users resent.

## 69. Status changes are claimed with one conditional UPDATE
**Decision:** Every "only if it's still X" step is a single `UPDATE ... WHERE id = ? AND status = ?` whose affected-row count says who won (`claim()` in `engine/executor.py`): deciding an approval (`pending` → decided), starting a run (`queued` → `running`) and resuming one (`waiting_approval` → `running`). The earlier read-then-write checks stay only to give a friendly message.
**Why:** Reading a status and then writing it is two steps, so two clicks, two browser tabs or a job delivered twice could both read "pending" and both carry on, and the customer would get the same email twice. The database already serialises single-row updates, so this closes the gap without locks, a queue feature or new infrastructure, and works the same on SQLite and Postgres. A test reproduces the race with two sessions.

## 70. pgvector removed
**Decision:** The pgvector package, the `CREATE EXTENSION vector` on startup and the pgvector Docker image were removed; local Postgres is plain `postgres:16`.
**Why:** Retrieval is BM25 over about 20 passages (decision 15), so nothing ever used vectors, and listing an unused technology misrepresents the project. The startup extension call was also a real bug: the app would refuse to start on any Postgres without pgvector installed, including most free hosted databases. Embeddings can come back, with a measurement, if the knowledge base grows.

## 71. Retries never repeat what can't be undone, and keep the failed attempt
**Decision:** An automation declares its `irreversible_steps` (the Lead Handler and Follow-up Nudge: `send`). A failed run that already completed one of them can't be retried from the start (409 with the reason). An allowed retry moves the failed attempt's steps into `output.previous_attempts` (status, error, model, duration, cost per step) instead of deleting them. On startup, runs that have been `running` for over 10 minutes are marked failed as interrupted, and their lead is marked failed.
**Why:** Retry re-runs from intake. If the reply was emailed and only saving the lead failed, a retry would email the customer again, which is worse than the original failure. Deleting the failed steps also threw away the trace needed to understand the failure. And a run lives in one process: if that process dies (a deploy, a crash, the free plan sleeping), nothing else would ever finish it, so it would say "running" forever. The 10-minute margin leaves a separate worker's in-progress job alone (jobs time out after 5).

## 72. Wrong passwords are rate limited by the address the proxy saw
**Decision:** Five wrong passwords from one address lock that address out for 15 minutes (429 with Retry-After); a correct login clears its count. The visitor's address is the last `X-Forwarded-For` entry, which Render's proxy appends, and the same helper now feeds the contact form and Try-it limits.
**Why:** Without a limit the owner password could be guessed at full speed. Counting only failures means the owner never notices. Earlier code used the first `X-Forwarded-For` entry, which the visitor controls, so anyone could dodge every per-IP limit by sending a made-up header. Limits are in memory: one server, and resetting on restart is acceptable for slowing guessing; several servers would move them to Redis.

## 73. Follow-up Nudge: one gentle follow-up, exactly once
**Decision:** A third automation. n8n calls `POST /api/follow-ups/scan` every morning; it finds hot and warm leads we replied to by email between 2 and 14 days ago who haven't written again, and starts one run per lead. The run re-checks the lead, drafts a short follow-up in the customer's language with the stronger model, then uses the Lead Handler's own fact check and the owner's Rules page (shared `judge_reply` and `decide_route`), so it can send alone, or hold the draft (translated if needed) in Needs you. Each lead is claimed as `follow_up:<lead id>` in `inbound_messages`, so it gets at most one follow-up ever, even if scans overlap, and one the owner skips is never offered again. Website-chat leads are left out (there's no way to write to them later).
**Why:** Quiet leads are where agencies lose money, and a follow-up is the most common manual chore after the first reply. Reusing the claim table, the fact check and the rules means the new automation added no new safety logic and no engine changes, which is also the proof that the hub design works: a second customer-facing automation is a class, a registry entry and a trigger.

## 74. The digest's "Today" list: code builds the tasks, the AI only orders them
**Decision:** The Daily Digest now opens with up to three tasks for today, each built by code from a database row: replies or follow-ups waiting (with how long), hot leads who asked for a call, hot leads still quiet after their follow-up, failed runs. The AI receives the list with ids and answers with ids in order plus a short reason; unknown ids are dropped, a reason containing a digit is dropped, and code's own order fills any gap or replaces the AI entirely if the call fails. The same list (in code's order, no AI) is shown on Home.
**Why:** "What should I do first?" is the useful part of a morning summary, and ordering by value and urgency is a judgement the model is good at. But a model writing the tasks could invent a lead, a name or an amount in an email the owner acts on. Restricting it to choosing from ids makes that impossible by construction rather than by prompt, which is the same rule as everywhere else in AutoHub: the model advises, code decides what's true.

## 75. The tests also run on Postgres
**Decision:** `TEST_DATABASE_URL` points the test suite at a Postgres database (wiped first), and CI runs it against a Postgres service container alongside the SQLite run.
**Why:** The live demo uses SQLite and local development uses Postgres, and the two differ in ways tests catch: running the suite on Postgres found that Postgres returns times in its server's time zone, which put runs on the wrong day in the weekly chart (now converted to UTC before bucketing), and the pgvector startup failure (decision 70).

## Known trade-offs to revisit
- **One owner account.** Login has a single owner password; a business with staff would need user accounts and an audit trail of who approved what.
- **Prices hard-coded.** The pricing table must be updated when Groq changes rates; unknown models are flagged as unpriced rather than shown as free.
