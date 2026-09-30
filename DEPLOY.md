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
   - `SECRET_KEY` is generated for you.
4. Deploy. Then open `/healthz`, which should say `ok`.

## 3. Check it works
- Sign up as a student with your `@fsu.edu` address, open the confirmation email, and confirm.
- Sign up as an employer with another address and submit a listing.
- Log in at `/admin` and approve it. It should appear on the board, and the Apply link should show only while you're logged in as a student.

## 4. Optional
- **Bot check:** create a Cloudflare Turnstile widget for your hostname and add `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET`.
- **Custom domain:** add it in Render → Settings → Custom Domains, then update `BASE_URL`.

## Backups
- **Daily copies:** once a day the app purges expired data and saves a consistent copy of the database to `/data/backups`, keeping the newest 14 (`BACKUP_KEEP`). These protect against mistakes like a bad delete.
- **Disk snapshots:** Render also snapshots persistent disks. Check the disk's settings in Render to confirm how often and for how long.
- **Off-site copy:** for a copy outside Render, open a Render shell and run `python backup.py --latest` to find the newest file, then download it.

## Limits to know
- **One instance only:** rate limits are kept in memory, and SQLite lives on one disk. Scaling to several instances means moving to Postgres and Redis first.
- **Student check:** it proves someone controls an `@fsu.edu` mailbox, not that they're currently enrolled. FSU single sign-on or SheerID is the real fix.
