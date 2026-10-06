# Going live on Render

The app is ready for production. It refuses to start unless every required setting below is present and strong.

## 1. Email first
Confirmation and password-reset emails need an SMTP provider, and the site won't start without one. Pick a provider, verify the domain you'll send from by adding the DNS records it gives you, then copy its SMTP settings:

| Setting | Example (Brevo) | Example (Resend) |
|---|---|---|
| `SMTP_HOST` | `smtp-relay.brevo.com` | `smtp.resend.com` |
| `SMTP_PORT` | `587` | `465` with `SMTP_SSL=1` |
| `SMTP_USER` | your Brevo SMTP login | `resend` |
| `SMTP_PASSWORD` | your Brevo SMTP key | a Resend API key |
| `SMTP_FROM` | `NoleCareerShield <noreply@your-domain>` | same |

FSU mail is strict. Send only from a domain whose SPF and DKIM records are verified with the provider, or confirmation emails will land in junk.

## 2. Create the service
1. Push this repo to GitHub.
2. In Render, go to **New → Blueprint** and pick this repo. Render reads `render.yaml`: one web service on the Starter plan with a 1 GB disk at `/data`, which a persistent disk requires.
3. Render asks for the secret values, which are never stored in the repo:
   - `ADMIN_PASSWORD`: the reviewer password, 16+ characters, not used anywhere else.
   - `CONTACT_EMAIL`: shown on the Privacy and Report pages.
   - `BASE_URL`: the public address, such as `https://nolecareershield.onrender.com`. Every email link is built from this.
   - `SMTP_*`: the values from step 1.
   - `SECRET_KEY`, `SHARE_FEED_KEY` and `INBOUND_EMAIL_TOKEN` are generated for you.
   - Render also asks for the optional keys listed under step 4 (scam intel, partner sharing, SSO, the decoy desk). Leave any of them empty to keep that feature off.
4. Deploy. Then open `/healthz`, which should say `ok`.

## 3. Keep it private until launch
Set `PRIVATE_BETA_CODE` in Render to a phrase only your testers know. Every page then asks for it once per browser, search
engines are told not to index anything, and `robots.txt` blocks crawlers. The reviewer desk (`/admin`) still works with its
own password. Change the code to lock everyone out again; delete it to open the site.

Before you delete it:
- Open `/admin/client-ip` and check it shows your own public IP (not a Cloudflare or Render one).
- Run through step 4 below with real accounts, including email confirmation and password reset from a phone.
- Make sure the GitHub repo is private and the Render secrets are set (nothing secret is in the code).
- Have someone with legal training read `/privacy` and `/terms`.
- Decide on the domain (`BASE_URL`) and set up FSU single sign-on if FSU ITS will register the app.
- Check the backups (see Backups below) and download one off-site copy.

## 4. Check it works
- Sign up as a student with your `@fsu.edu` address, open the confirmation email, and confirm.
- Sign up as an employer with another address and submit a listing.
- Log in at `/admin` and approve it. It should appear on the board, and the Apply link should show only while you're logged in as a student.

## 5. Optional
- **AI features:** create a key at console.anthropic.com, set a monthly spend limit there, and add it as `ANTHROPIC_API_KEY`. `AI_DAILY_LIMIT` (per person, default 40) and `AI_SITE_DAILY_LIMIT` (default 3000) cap usage. Without a key everything still works on the built-in engines.
- **Bot check:** create a Cloudflare Turnstile widget for your hostname and add `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET`.
- **Scam intel:** `INTEL_NETWORK=1` (set by the blueprint) turns on domain age, SPF/DMARC, link expansion and the daily look-alike-domain watch. `URLHAUS_AUTH_KEY`, `SPAMHAUS_DQS_KEY`, `CHAINABUSE_API_KEY` and `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` each switch on one outside check. `INDICATOR_KEY` is optional (empty = derived from `SECRET_KEY`); set it only on a fresh install, because changing it later forgets the stored contact details.
- **Partner schools:** `SHARE_HMAC_KEY` (the same value at every school), `SHARE_FEED_KEY` (generated; give it to partners), `SHARE_SOURCE_NAME`, and `PEER_FEEDS` (`https://their-site/api/indicators|their-key`, comma-separated). `ARCHIVE_FEEDS` adds RSS/Atom feeds of published scams to the label queue weekly.
- **Forward-by-email:** point SendGrid or Mailgun inbound parse at `{BASE_URL}/inbound/email?token=<INBOUND_EMAIL_TOKEN>`.
- **Scam model:** the blueprint sets the defaults (`SCAM_MODEL`, `MODEL_AUTO_RELEASE`, `RETRAIN_*`, `RELEASE_*`, `LOW_RISK_SAMPLE_*`); `.env.example` explains each. `MODEL_AUTO_RELEASE=0` makes every release step wait for a reviewer. `SCAM_MODEL=off` runs rules only.
- **Decoy desk:** leave `DECOY_ENABLED` empty until FSU legal has signed off.
- **FSU single sign-on:** once FSU ITS registers the app, set `SSO_TENANT_ID`, `SSO_CLIENT_ID` and `SSO_CLIENT_SECRET`.
- **Custom domain:** add it in Render → Settings → Custom Domains, then update `BASE_URL`.

## Backups
- **Daily copies:** once a day the app purges expired data and saves a consistent copy of the database to `/data/backups`, keeping the newest 14 (`BACKUP_KEEP`). These protect against mistakes like a bad delete.
- **Disk snapshots:** Render also snapshots persistent disks. Check the disk's settings in Render to confirm how often and for how long.
- **Off-site copy:** for a copy outside Render, open a Render shell and run `python backup.py --latest` to find the newest file, then download it.

## Limits to know
- **One instance only:** SQLite (the data and the rate-limit store) lives on one disk, so the app runs on one server; several worker processes on it share the limits. Scaling to several servers means moving to Postgres and Redis first.
- **Student check:** it proves someone controls an `@fsu.edu` mailbox, not that they're currently enrolled. FSU single sign-on or SheerID is the real fix.
