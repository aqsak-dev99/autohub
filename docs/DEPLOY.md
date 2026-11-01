# Deploying AutoHub on Render (free)

The public demo is one free Render web service built from the `Dockerfile` at the repo root:
the API and the built dashboard in one container. Its SQLite database lives on the service's
own disk, which Render wipes whenever the service restarts or wakes up, so it reloads the
sample conversations every time. Nothing to clean, nothing that expires.

Good to know about the free plan: the service sleeps after 15 minutes without visitors and takes
about a minute to wake up. Open the link yourself a minute before an interview.

## Steps
1. Push the repo to GitHub (check `git status` first: `.env` must not be listed).
2. render.com → sign in with GitHub → **New +** → **Blueprint** → choose the `autohub` repo.
   Render reads `render.yaml` and shows one web service called `autohub`.
3. It asks for the two secret values (they're never stored in the repo):
   - `ADMIN_PASSWORD`: the password you'll use to log in as the owner. Make it long.
   - `GROQ_API_KEY`: your Groq key, so "Try it" gets real AI replies.
4. **Apply**. The first build takes about 5 minutes. When it says *Live*, open the `onrender.com` link.
5. Check: `https://<your-app>.onrender.com/health` shows `"status":"ok"`, the login page has
   **Explore the demo**, and **Try it** answers a message.

## What visitors can and can't do
| | Demo visitor | Owner (password) |
|---|---|---|
| See every page, Technical details, replays | ✓ | ✓ |
| Try it (10 an hour each, 150 a day in total) | ✓ | ✓ |
| Approve / edit / reject | only replies to their own Try it messages | ✓ |
| Save rules, retry runs | preview only | ✓ |

The demo never emails anyone (`SEND_MODE=dry_run`) and doesn't read the Gmail inbox
(n8n isn't running there). The website contact form is off unless `FORM_ALLOWED_ORIGINS` is set.

## Updating
Every push to `main` redeploys automatically. Database changes are Alembic migrations
(`backend/migrations`), applied on start.
