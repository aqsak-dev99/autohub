# Connecting email (Gmail)

About 10 minutes. AutoHub reads a Gmail inbox, turns each real enquiry into a Lead Handler run, and replies
in the same email thread. flowpath's contact-form leads get email replies too.

## 1. Use a Gmail account made for AutoHub
AutoHub reads **every unread email** in the inbox (from the last day) and may reply to it. Don't connect
your personal inbox. Create a new Gmail, e.g. `flowpath.leads.demo@gmail.com`. That address is also what
interviewers can email to try the demo.

> **No new account?** Use plus-addressing on your own Gmail: mail sent to `you+flowpath@gmail.com` arrives
> in your inbox. In Gmail, create a filter *To: you+flowpath@gmail.com → Skip the inbox, Apply label
> `flowpath`*, then set `IMAP_FOLDER=flowpath` so AutoHub only reads that label.

## 2. Create an app password
1. Sign in to the AutoHub Gmail → **myaccount.google.com → Security**.
2. Turn on **2-Step Verification** (Google requires it for app passwords).
3. Go to **myaccount.google.com/apppasswords**, name it `AutoHub`, click **Create**.
4. Copy the 16-letter password (the spaces don't matter). It's shown only once.

An app password works only for email, can be deleted any time, and doesn't expire unless you change the
account's password.

## 3. Settings in `.env`
```
SMTP_USERNAME=flowpath.leads.demo@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
EMAIL_FROM_NAME=flowpath
SEND_MODE=live
EMAIL_SEND_ALLOWLIST=you@gmail.com      # while testing: replies only to your own address
DIGEST_EMAIL_TO=you@gmail.com
```
Restart so the containers read them: `docker compose up --build --force-recreate`.

Leave `EMAIL_SEND_ALLOWLIST` set while testing. Empty it when you want anyone who writes in to get a reply
(for the public demo).

## 4. Test by hand
1. From your personal email, send the AutoHub address something like:
   *Subject: Instagram ads for my restaurant. Body: Hi, I run a restaurant in DHA. What would social media
   and ads cost per month?*
2. Check the inbox once:
   ```bash
   docker compose exec api python scripts/poll_inbox.py
   ```
   You should see `"started": 1`.
3. Within about 20 seconds the reply arrives in your personal inbox, in the same thread. If it needs review,
   it waits in `GET /api/approvals`; approving it sends the email.

## 5. Check automatically every minute (n8n)
1. Open n8n (Ports tab → **5678**).
2. **Workflows → Import from file** → `n8n/workflows/inbox_check.json` → switch it **Active**.

## If it doesn't work
| Symptom | Cause |
|---|---|
| Poll returns **502 … IMAP login** | Wrong app password, or 2-Step Verification is off. Use the 16-letter app password, not the account password. |
| Poll returns **502 … folder** | `IMAP_FOLDER` doesn't exist. Use `INBOX` or the exact label name. |
| `"fetched": 0` | The email was already read (open it in Gmail → mark as unread), or it's older than `EMAIL_POLL_SINCE_DAYS`. |
| `"skipped"` lists your email | It looked automated (no-reply sender, auto-reply, newsletter). Send from a normal address. |
| Run fails at `send`, code **535** | Gmail rejected the SMTP login: same fix as the IMAP login. |
| Reply lands in **spam** | Normal for a brand-new Gmail. Mark it "Not spam" once; it improves quickly. |
| Run succeeds but no email | The `send` step says `dry_run`: check `SEND_MODE=live` and `EMAIL_SEND_ALLOWLIST`. |

Free Gmail accounts can send about 500 emails a day, far more than a demo needs.
