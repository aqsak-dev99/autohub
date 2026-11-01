# Eval results

_Run 01 Nov 2026 · openai/gpt-oss-20b + openai/gpt-oss-120b · 40 messages, 0 errors · median 19.5 s per reply · about $0.000901 per message_

| | English | Roman Urdu | Urdu | Arabic | All |
|---|---|---|---|---|---|
| Understood the request (intent) | 100% | 90% | 100% | 90% | 95% |
| Detected the language | 90% | 90% | 100% | 80% | 90% |
| Picked out the services | 100% | 100% | 100% | 100% | 100% |
| Read the budget correctly | 100% | 100% | 100% | 100% | 100% |
| Fact check caught a planted false claim | 100% | 100% | 100% | 50% | 88% |
| Fact check false alarms on clean replies | 0% | 0% | 0% | 50% | 12% |
| Replies sent on their own (where allowed) | 100% | 86% | – | – | 93% |
| **Sent alone when it should have asked** | 0 | 0 | 0 | 0 | **0** |

Replies rewritten automatically to remove an unsupported claim: 5.

## What this says about the review rules
- **English:** good enough to stop reviewing every reply by default.
- **Roman Urdu:** good enough to stop reviewing every reply by default.
- **Urdu:** good enough to stop reviewing every reply by default.
- **Arabic:** keep reviewing replies for now.

How it's measured: `backend/evals/run.py`. Sets: `leads.jsonl` (40 labelled messages, 10 per language) and `checker.jsonl` (16 replies, half with a planted false claim).
