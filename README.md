# NoleCareerShield

A scam-screened job board for FSU students. Every listing is **scored by a
transparent scam detector and then approved by a human** before it appears.

Independent student project. Not affiliated with, sponsored by, or endorsed by
Florida State University; it uses no university marks or logos.

## The model

- **Anyone can browse** the listings without an account.
- **Students** create an account with a confirmed `@fsu.edu` address to see how to
  apply (the Apply link and contact are hidden from logged-out visitors).
- **Employers** create an account (any email, confirmed by link) to send a listing.
  Clicking *Submit for review* while logged out takes them to employer log in / sign
  up and the listing sends by itself once they are in. Submitting is not publishing.
- **Every submission is scored** by the rule-based detector in `scam_detector/`,
  then waits in a review queue. Nothing goes live until a person approves it.
- **Any live listing can be removed** by a reviewer at any time, and listings
  expire on their own (default 90 days).

Accounts keep bots and scrapers away from student contact details and give every
listing an owner. They do not replace review: gating by *who someone is* is not the
same as vetting *what they post*, so every listing is still scanned and approved.

## Privacy by design

An account stores an email address, the role (student or employer) and a salted
scrypt password hash. No name, resume, profile, messaging, analytics, ad tech,
third-party fonts, and no third-party scripts unless you turn on Cloudflare Turnstile.
Cookies: a login cookie (`usession`, 7 days), a short-lived saved-listing cookie
(`draft`, 3 days, only while a logged-out poster signs in) and the reviewer session
cookie; all HttpOnly, Secure in production. Confirmation and reset tokens and login
session ids are stored only as SHA-256 hashes. Unconfirmed accounts are deleted after
7 days; rejected/removed listings after 90. See `/privacy`.

## Accounts and sign-in

| | Students | Employers |
|---|---|---|
| Log in / sign up | `/login/student`, `/signup/student` | `/login/employer`, `/signup/employer` |
| Email allowed | exactly `@fsu.edu` (lookalikes such as `fsu.edu.evil.com` or `sub.fsu.edu` are refused) | any |
| Needs | confirmed email link + password | confirmed email link + password |
| Unlocks | Apply link and contact on listings | submitting listings |

Password rule (both): 8+ characters with a capital letter, a number and a symbol; not a
common word and not containing the email name. The sign-up page checks live; the
server enforces it. Forgot password emails a one-hour link; a new password ends every
existing login.

Design choices worth knowing: sign-up, resend and forgot-password give the same answer
whether or not the address is registered; login errors are identical for wrong
password and unknown email; confirmation links open a page with a button and ask for
the password, so an email scanner cannot confirm an account and a stranger who signs up
with your address cannot get you to confirm *their* password.

**What "verified student" means here.** The app proves the person controls an
`@fsu.edu` mailbox. It does not prove current enrollment (staff, alumni with forwarding
and some affiliates also hold `fsu.edu` addresses). Services such as Student Beans use
an enrollment-data provider (SheerID) or the school's single sign-on. For a university
deployment, replace the email check with FSU SSO (SAML/OIDC) or a SheerID
integration; both need FSU IT or a commercial agreement, so they cannot be built
without them. The seam is `accounts.is_fsu_email` and the student sign-up route in
`app.py`.

**Reviewing without a human.** Not built on purpose. Today each approve/reject is a
labeled example; the queue shows how often the detector agreed with reviewers. Turning
on auto-publish for low-scoring listings should wait until that agreement figure is
measured on enough real reviewed listings, and should keep sampling a share of
auto-approved listings for human audit. Until then a person approves everything.

## How the detector keeps getting better

Reviewers are the training signal. Rejecting or removing a listing asks why (scam,
aggregator, other); approving records "legit". The review queue shows how often the
detector agreed with those decisions and how many bad listings it missed.

Once a month (rejected rows are purged after 90 days), in your working copy with a copy of the database, not inside the deployed container. Commit the updated rulepack and redeploy:

```bash
python export_labeled.py --db /data/jobs.db -o labeled.jsonl
python -m scam_detector.tools.mine_candidates labeled.jsonl scam_detector/data/*.jsonl -o proposed.json
python -m scam_detector.tools.regress --candidate proposed.json          # must pass
python -m scam_detector.tools.regress --candidate proposed.json --promote  # after you read it
```

A candidate rule that flags any legitimate posting in the test corpora is refused,
and nothing is added without a person promoting it. Details and the reasoning are in
`scam_detector/ADAPTING.md`. Aggregator / lead-generation listings are flagged for the
reviewer with their own explanation but never counted as scams.

## Run locally

```bash
pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000. The review queue is at `/admin`; in development the
password defaults to `changeme` (production refuses this).

## Configuration

All configuration is environment variables (see `.env.example`). Nothing
sensitive is in the code or the repository.

| Variable | Production | Purpose |
|---|---|---|
| `ENV` | `production` | Enables strict startup checks, HSTS, Secure cookies |
| `ADMIN_PASSWORD` | required, 12+ chars | Reviewer sign-in |
| `SECRET_KEY` | required, 32+ chars | Signs CSRF tokens |
| `CONTACT_EMAIL` | required | Shown on Privacy and Report pages |
| `DB_PATH` | `/data/jobs.db` | SQLite location (persistent disk) |
| `BASE_URL` | required, `https://...` | Public address; every email link is built from it |
| `SMTP_HOST`, `SMTP_FROM` | required | Outgoing mail server and From address (`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_PORT`, `SMTP_SSL=1` optional) |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET` | optional, both or neither | Cloudflare Turnstile bot check on sign-up, login and reset forms |
| `OUTBOX_LOG` | development only | File where dev-mode emails are written instead of sent |
| `TRUST_PROXY` | `1` behind one proxy | Use the proxy's client IP for rate limits |
| `LISTING_TTL_DAYS` | 90 | How long approved listings show |
| `PURGE_REJECTED_DAYS` | 90 | Retention for rejected/removed rows |

In production the app **refuses to start** if `ADMIN_PASSWORD`, `SECRET_KEY`,
`CONTACT_EMAIL`, `BASE_URL` (https) or the SMTP settings are missing or weak. Without
`SMTP_HOST` in development, emails are not sent: read the confirmation link in
`outbox.log`.

## Deploy

A `Dockerfile` and Render blueprint (`render.yaml`) are included. On Render:
New > Blueprint > pick this repo, enter `ADMIN_PASSWORD`, `CONTACT_EMAIL`,
`BASE_URL`, `SMTP_HOST` and `SMTP_FROM` (plus `SMTP_USER`/`SMTP_PASSWORD`) when prompted, then attach your domain. TLS is terminated by the host. Railway
and Fly.io work the same way from the Dockerfile; set the variables above and
mount a volume at `/data`. Static hosts (Wix, GitHub Pages) cannot run this.

Do not deploy under an FSU name or domain without written permission from the
university.

## Security controls

- Reviewer login 5 attempts per 15 minutes per IP. Account login 10 per 15 minutes per
  IP and 8 per account; sign-ups 10/hour per IP; emails 3/hour per address.
  Submissions 20/hour, browsing 120/minute. Sliding window, in memory.
- CSRF tokens on every form; admin tokens are bound to the admin session.
- Honeypot field and time-limited form tokens against bots.
- Server-side length caps, control-character stripping, URL and enum
  validation on every field. All output is HTML-escaped.
- Strict Content-Security-Policy (no scripts, no external resources),
  `X-Frame-Options: DENY`, `nosniff`, no-referrer, HSTS in production.
- API docs/OpenAPI disabled; admin pages are `no-store` and `noindex`.
- Constant-time password compare; sessions are random 256-bit tokens with expiry.

Run the tests: `pip install -r requirements-dev.txt && python -m pytest -q`

## Known limits (honest list)

- Rate limiting is per process. Running more than one worker or replica needs a
  shared store (Redis) so limits apply globally.
- One shared reviewer password. A university deployment should use SSO for reviewers
  (staff) and for student verification (see above).
- SQLite on one disk. Move to managed Postgres for multi-instance or high
  traffic.
- Scoring is rules plus reviewer judgment. The detector's numbers on real,
  unseen postings are unknown: the only real data so far is 9 of the author's own
  listings plus 5 excerpts from university alerts, all read while the rules were
  written (see `scam_detector/README.md` for the full table and caveats). Before the
  rework it missed every one of the external excerpts and wrongly blocked several
  legitimate postings, so the human review step is not optional and the queue's
  agreement figure is the number to watch.
- Aggregator / lead-generation listings are largely identified by the link and the
  apply flow, not the text; from a pasted description alone most are invisible.
- No audit log of reviewer actions yet.
- Email confirmation proves a mailbox, not a person: employer accounts are not
  identity-checked; the review step is what vets them.
- No "Continue with Google" button (needs a Google OAuth client registered to the
  operator). No two-factor sign-in yet.

## Trademark

Original emblem and garnet/gold palette only. No FSU seal or logos. "Nole" is
evocative, not a claim of affiliation. Official names or marks only with
university permission.
