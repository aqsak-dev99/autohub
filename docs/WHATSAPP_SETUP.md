# Connecting WhatsApp

AutoHub supports two providers behind the same code, chosen with `WHATSAPP_PROVIDER`:
- **meta** (default): Meta's official WhatsApp Cloud API. Free test number, verified through WhatsApp itself.
- **twilio**: Twilio's sandbox. Built and tested first, but Twilio's account verification doesn't accept
  Pakistani numbers, so the live demo uses Meta.

## Meta WhatsApp Cloud API (about 20 minutes)

### 1. Meta app and test number
1. Facebook account → **developers.facebook.com** → **Get Started** → register as a developer.
2. **My Apps → Create App** → name `AutoHub` → use case **Connect with customers through WhatsApp** →
   create a business portfolio when asked (a name is enough) → **Create app**.
3. **Start using the API** → on **API Setup**, accept the defaults to create the WhatsApp account.
4. Note the **Phone number ID** and click **Generate access token**.
5. In **To → Manage phone number list**, add your own WhatsApp number (Meta sends the code by WhatsApp).
6. **Send message** → "Hello World" arrives on your phone → **reply "hi"** (opens the 24-hour window).
7. **App settings → Basic → App secret → Show**: note it.

### 2. Settings in `.env`
```
WHATSAPP_PROVIDER=meta
META_ACCESS_TOKEN=EAA...
META_PHONE_NUMBER_ID=1234567890
META_APP_SECRET=abc123...
META_VERIFY_TOKEN=autohub-verify-7k2p9      # make up any string; you'll type it into Meta in step 4
SEND_MODE=live
LIVE_SEND_ALLOWLIST=+923001234567           # your own number only
DIGEST_WHATSAPP_TO=+923001234567
```
Then restart so the containers read them: `docker compose up --build --force-recreate`.

### 3. Make the API reachable
**Ports** tab → right-click port **8000** → **Port Visibility → Public** → copy its address,
e.g. `https://moonlit-cape-abc123-8000.app.github.dev`.

> While public, anyone with the address can reach the API. Webhooks are protected by signatures, but the
> approval endpoints aren't yet (authentication comes with deployment). Set it back to **Private** afterwards.

### 4. Point Meta's webhook at AutoHub
The stack must be running for this step: Meta checks the URL immediately.
1. App dashboard → **WhatsApp → Configuration** → **Webhook → Edit**.
2. **Callback URL:** `https://<your-address>/api/webhooks/meta/whatsapp`
3. **Verify token:** exactly your `META_VERIFY_TOKEN` → **Verify and save**.
4. Under **Webhook fields**, click **Manage** and **subscribe to `messages`**.

### 5. Test
Send *"Salam, Instagram ads ka kitna charge hai?"* to the test number from your phone. Within about
10–20 seconds the reply arrives, or it waits in `GET /api/approvals` if it needs review (approving sends it).

### If it doesn't work
| Symptom | Cause |
|---|---|
| Meta says it **couldn't validate the callback URL** | Port 8000 isn't public, the stack isn't running, or the verify token doesn't match `META_VERIFY_TOKEN` exactly. |
| Nothing happens when you message | Webhook field `messages` isn't subscribed, or your number isn't in the test number's recipient list. |
| API logs show **403 Invalid signature** | `META_APP_SECRET` is wrong (App settings → Basic). |
| Run fails at `send`, code **190** | The temporary access token expired (they last about a day). Generate a new one and restart, or create a permanent one (below). |
| Run fails at `send`, code **131047** | WhatsApp only allows free-form replies within 24 hours of the customer's last message. Message the number again. |
| Run fails at `send`, code **131030** | The recipient isn't in the test number's allowed list. |
| Run succeeds but no message | The `send` step says `dry_run`: check `SEND_MODE=live` and the allowlist. |

### Permanent access token (optional)
The token from API Setup expires quickly. For a token that lasts: **Business Settings → Users → System users →
Add** (Admin) → **Assign assets**: your app (Full control) and WhatsApp account (Full control) →
**Generate token** for the app with `whatsapp_business_messaging` and `whatsapp_business_management` →
put it in `META_ACCESS_TOKEN`.

## Twilio sandbox (alternative)
1. twilio.com → **Messaging → Try it out → Send a WhatsApp message** → join the sandbox from your phone.
2. `.env`: `WHATSAPP_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, plus `SEND_MODE`,
   `LIVE_SEND_ALLOWLIST`, `DIGEST_WHATSAPP_TO` as above.
3. Port 8000 public → **Sandbox settings → When a message comes in:**
   `https://<your-address>/api/webhooks/twilio/whatsapp` (POST).
4. If Twilio's logs show 403, set `PUBLIC_BASE_URL` to your exact address and restart.

## Daily digest (n8n)
1. Open n8n (Ports tab → **5678**) and create the owner account.
2. **Workflows → Import from file** → `n8n/workflows/daily_digest.json`.
3. **Execute workflow** to try it now, then switch it **Active** for 9 am daily.

The digest goes to `DIGEST_WHATSAPP_TO`. WhatsApp only delivers it within 24 hours of your last message to the
business number; otherwise it's still saved on the run.
