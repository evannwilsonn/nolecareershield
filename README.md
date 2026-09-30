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

## The student network

Signed-in students and employers get an app layout (sidebar, bento home) with:

| Feature | Where | What it does |
|---|---|---|
| Profile setup | `/profile/setup` | 3 steps for students (about, skills and goals, resume and privacy), 2 for employers. New accounts land here after confirming their email. |
| Profiles | `/profile`, `/u/{id}`, `/company/{id}` | A LinkedIn-style header and sections (About, Experience, Education, Projects, Skills, Certifications, Organizations, Courses, Languages) with a Handshake-style "Looking for" column. "Fill from resume" (`resume_parse.py`) turns an uploaded resume into editable entries. Other students see only the basics; approved employers also see the sections. Employers are reviewed by a person before they can message students or post. |
| Company pages | `/company/{id}` | LinkedIn-style company page: tagline, industry, size, founding year, website and LinkedIn, about, how they work with FSU students, roles they hire for, perks, open listings, hiring at a glance (reply rate, typical reply time) and a trust score. |
| Employer trust score | company pages, listings, reviewer queue | 0-100, higher is safer (`employer_page.py`): verification 30, listing record 25, conduct with students 20, responsiveness 15, profile 10. Capped below 50 until a reviewer approves them or if a message matched scam-only patterns, below 70 with an open report or a flagged message, and at 30 after a listing is rejected as a scam. The listing number is now labelled "scam risk" so the two scales can't be confused. |
| Visitors and employers | `/`, `/employers` | Listings are private: logged-out visitors see a home-page teaser (title, company, category) and every job link goes to sign-in and back. Employers have their own door: a `/employers` page and separate employer log-in and sign-up pages. |
| Find students | `/talent` | Approved employers search students who opted in. |
| Hiring tools | `/hiring`, `/hiring/{id}` | For each listing: students who viewed it and clicked Apply (totals only), students who messaged, ranked matches of every visible student using the same fit score and evidence students see, one-click "Invite to apply" (a prefilled, scanned message), and a candidate tracker with stages and private notes (`hiring.py`). |
| Messaging | `/messages` | Student ↔ approved employer only. Every message is scanned when sent: scam-only patterns are held for a reviewer, suspicious ones are delivered with a warning and a link to the full check. Links aren't clickable; block and report on every thread; emails never contain message text. |
| Scam check | `/check` | Two tabs: a message, or a job listing found anywhere (title, company, description, apply link and contact, scored exactly like a listing submitted to the board; the link is read, never opened). Public, so anyone can check a message or listing (10 a day for visitors). Visitors see the verdict and up to three plain reasons; signed-in FSU students and approved employers see every signal, the exact words it caught, link and sender checks, and can check messages from their inbox. Visitors can say which school they want it at (`/admin/schools`); only the school name is stored. Rules decide the verdict; the optional AI opinion can only add caution. |
| Job assistant | `/assistant` | Plain-language job search and "what fits my resume?", in the style of Indeed's Job Scout. It only ever shows approved listings: the AI cites listing IDs and the server drops any that aren't live. Pasted messages go to the scam check. |
| Job fit | every listing | A 0-100 score from the whole profile (`fit.py`): skills 35, experience and projects 25, education 15, certifications 10, keywords 10, preferences 10. Parts a job doesn't ask about are left out. Each score shows where in the profile the evidence was found and a met / missing / unknown checklist of the job's requirements. It's worked out when the page opens and never stored or shown to employers. |
| Resume studio | `/resume` | Upload PDF, Word (.docx) or text. Score (six categories), line-by-line rewrites that never add facts, an editor, tailoring to any listing or pasted job (also built into every listing page), saved versions, .docx download. |
| FSU feed | `/feed` | Only confirmed FSU students and approved employers can read or post. Employer posts must pass an FSU-relevance check (ads rejected on the spot) and a reviewer. Student posts with scam signals are held. Three reports hide a post. |
| Reviewer queues | `/admin/*` | Listings, employers, feed posts, held messages, reports, and messages students sent in from the checker. |

**AI is optional.** Set `ANTHROPIC_API_KEY` to use Claude for the assistant, resume
review and tailoring, the scam checker's second opinion and feed moderation. Without
it, every feature runs on the built-in engines (`matching.py`, `resume_engine.py`,
the scam detector). Per-account and site-wide daily caps bound the cost, and all
user-written text goes to the model as tagged data, never as instructions.

**How consistent is the scam check?** The same text always gets the same rule verdict.
On the 103 hand-labeled real listings in `scam_detector/data/field_2026_09.jsonl`:
35 of 42 scams get "likely a scam" or "scam", 41 of 42 get at least "be careful",
and none of the 49 legitimate listings get any warning. Most of those scams were
university email templates, so treat this as a sanity check, not a promise.

## Interactive demo

`python demo/build.py` writes `demo/index.html`, a single-file, no-server version of the whole site (not kept in git, since it embeds the landing footage): the job board, profiles and
setup, messaging, the scam check, the job assistant, the resume studio, the FSU feed and every reviewer
queue, running on sample data in the browser. It uses the real stylesheet (`ui.py`), the real rules
(`scam_detector/rulepack/core.json`) and `demo/engine.js`, a port of the Python engines. 
`tests/test_demo_engine.py` runs that port against the Python on every labeled corpus and fails on any
difference in a score, verdict, finding, resume score, rewrite, parsed resume or job fit score. The demo reads PDFs with
pdf.js (loaded from cdnjs only when someone uploads one) and Word files with the browser's own zip inflater. Rebuild after changing the site.

## Privacy by design

An account stores an email address, the role (student or employer) and a salted
scrypt password hash, plus whatever the person adds to their profile. Students
control who sees their profile and resume, can download everything as JSON and can
delete their account from `/profile`. No analytics, ad tech, third-party fonts, and
no third-party scripts unless you turn on Cloudflare Turnstile.
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
| `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_DAILY_LIMIT`, `AI_SITE_DAILY_LIMIT` | optional | AI for the career assistant, resume tools and the scam check's second opinion, with per-person and site-wide daily caps |
| `INTEL_NETWORK`, `INDICATOR_KEY`, `URLHAUS_AUTH_KEY`, `SPAMHAUS_DQS_KEY`, `CHAINABUSE_API_KEY`, `TWILIO_*` | optional | Scam intel: network lookups, the hashed contact-detail memory, and outside reputation checks |
| `SHARE_HMAC_KEY`, `SHARE_FEED_KEY`, `SHARE_SOURCE_NAME`, `PEER_FEEDS`, `ARCHIVE_FEEDS` | optional | Sharing confirmed-scam details with partner schools and pulling public scam feeds |
| `INBOUND_EMAIL_TOKEN`, `DECOY_ENABLED` | optional | Forward-by-email checks; the decoy desk (off until FSU legal signs off) |
| `SCAM_MODEL`, `SCAM_RULEPACK_EXTRA`, `MODEL_AUTO_RELEASE`, `RETRAIN_*`, `RELEASE_*`, `LOW_RISK_SAMPLE_*` | defaults in `.env.example` | The learned model, hot-fix rules, retraining triggers, staged release and random sampling of safe results |
| `SSO_NAME`, `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` | optional | FSU single sign-on |

In production the app **refuses to start** if `ADMIN_PASSWORD`, `SECRET_KEY`,
`CONTACT_EMAIL`, `BASE_URL` (https) or the SMTP settings are missing or weak. Without
`SMTP_HOST` in development, emails are not sent: read the confirmation link in
`outbox.log`.

**FSU single sign-on (optional).** Sign-in starts with one email box, like Handshake. An @fsu.edu address goes to
"Continue to FSU single sign-on" (OpenID Connect with PKCE against FSU's Microsoft Entra tenant, so FSU's own page and
Duo handle the password) when `SSO_TENANT_ID`, `SSO_CLIENT_ID` and `SSO_CLIENT_SECRET` are set; any other address goes
to the employer login. FSU ITS has to register the app (redirect URI `{BASE_URL}/sso/callback`) before this can be
switched on; until then students use email and password. `sso.py` checks the state, nonce, token signature, issuer,
audience, expiry and tenant, and that the address is exactly @fsu.edu.

## Deploy

A `Dockerfile` and Render blueprint (`render.yaml`) are included. On Render:
New > Blueprint > pick this repo, enter `ADMIN_PASSWORD`, `CONTACT_EMAIL`,
`BASE_URL`, `SMTP_HOST` and `SMTP_FROM` (plus `SMTP_USER`/`SMTP_PASSWORD`) when prompted (the optional keys can stay empty; see `DEPLOY.md`), then attach your domain. TLS is terminated by the host. Railway
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
- Messaging updates by polling every 8 seconds, not live sockets. Fine for a
  campus-sized site.
- The built-in job assistant is keyword and skill matching. It's useful, but the
  plain-language experience really needs the AI key.
- The scam check can't see what happens off the platform (a real company's
  recruiter who later asks for money). It warns, it doesn't guarantee.
- Email confirmation proves a mailbox, not a person: employer accounts are not
  identity-checked; the review step is what vets them.
- No "Continue with Google" button (needs a Google OAuth client registered to the
  operator). No two-factor sign-in yet.

## Trademark

Original emblem and garnet/gold palette only. No FSU seal or logos. "Nole" is
evocative, not a claim of affiliation. Official names or marks only with
university permission.
