# NoleCareerShield: handoff (Sept 30, 2026)

Read this first in a new chat. The README has the full feature table and settings; this file is where things
stand, what was decided and why, and what's next.

## Where everything lives

- **Code:** github.com/evannwilsonn/nolecareershield (branch `main`). Python / FastAPI / SQLite, deployed on Render (`render.yaml`, `DEPLOY.md`).
- **Demo:** `demo/index.html` (full page) and `demo/NoleCareerShield_Demo.html` (body only, published as the Claude artifact
  "NoleCareerShield Demo (Copy)"). Rebuild with `python demo/build.py` after any site change. The demo runs the real
  scam rules and a JS port of the engines; `tests/test_demo_engine.py` fails if the port disagrees with the Python.
- **Installer:** `setup_jobboard.py` holds every tracked file. Regenerate it before each commit (see the snippet in git history).
- **Tests:** `python -m pytest -q` (135 passing at handoff).

## Rules Evan set (keep them)

- No passwords, keys or phone numbers in code or git. Secrets live only in Render's environment settings.
- Nothing sensitive exposed in the front end.
- Replies to Evan: short, plain paragraphs.

## What the site does now

- **Students (FSU only):** email-first sign-in like Handshake. FSU single sign-on is built but switched off until FSU ITS
  registers the app (see Next). LinkedIn x Handshake profiles filled from a PDF/Word/text resume; a 0-100 fit score on
  every job from the whole profile; tailoring on every listing; resume studio; job assistant; messaging with scam
  scanning; FSU-only feed.
- **Employers:** own entrance at `/employers` with separate log-in and sign-up. Reviewer approval required. Detailed company
  pages with a trust score (0-100, **higher is safer**). Hiring tools per listing: ranked student matches, one-click
  invite, candidate tracker with stages and private notes, views / Apply clicks / messages.
- **Visitors:** listings are private. The home page shows a teaser (title, company, category, counts) and every job link
  goes to sign-in and back. The scam check is public with two tabs, **A job listing** (default) and **A message**.
  Visitors get the verdict and up to three reasons, 10 checks a day; FSU students and approved employers get the full
  evidence. Visitors can name a school they want it at (only the name is stored; reviewer tab "School requests").
- **Reviewers:** `/admin` queues for listings, employers (with trust score), feed, held messages, reports, sent-in checks
  and school requests.

## Decisions and why

- **Listings behind login:** "only verified FSU students see these" is the pitch to employers, and it keeps scrapers and
  scammers from copying real postings. Cost: no search traffic to job pages, which is fine for a campus-only board.
- **Scam check stays public but tiered:** it's the best advertisement and a lead source for other schools; the public view
  is enough to spot a scam but not enough to tune one until it passes.
- **Trust score 100 = good; listing number is labelled "scam risk":** two opposite scales must never share a label.
- **Employer view counts are totals only:** employers never see which students viewed or clicked Apply. Students appear in
  a tracker only when they message, are invited, or are saved from matches.
- **"Let approved employers find me" is checked by default at setup;** students can uncheck it. Evan questioned whether
  students should control visibility at all. Open question, not changed yet.
- **Demo never imitates FSU's sign-in page;** it shows a labelled stand-in, because a copy of a university login is what
  phishing looks like.
- **An "applicant tracker" that scores students on reply speed was dropped** (Evan's call after discussing privacy and
  hiring-law concerns).

## Next / waiting on someone

1. **FSU single sign-on:** ask FSU ITS to register NoleCareerShield in FSU's Microsoft Entra tenant with redirect URI
   `https://<site>/sso/callback`, then set `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` on Render.
2. Decide whether students keep the three privacy toggles (visible to employers, share resume, allow messages).
3. Optional: `ANTHROPIC_API_KEY` on Render turns on AI for the assistant, resume tools and the scam check's second opinion.
4. Ideas raised but not built: a "usually replies within a day" badge; applicant-fraud flags for employers (fake or
   duplicate student accounts).
