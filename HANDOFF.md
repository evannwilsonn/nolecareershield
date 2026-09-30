# NoleCareerShield: handoff (Sept 30, 2026)

Read this first in a new chat. The README has the full feature table and settings; this file is where things
stand, what was decided and why, and what's next.

## Where everything lives

- **Code:** github.com/evannwilsonn/nolecareershield (branch `main`). Python / FastAPI / SQLite, deployed on Render (`render.yaml`, `DEPLOY.md`).
- **Demo:** `python demo/build.py` writes `demo/index.html` (full page) and `demo/NoleCareerShield_Demo.html` (body only,
  published as the Claude artifact "NoleCareerShield Demo (Copy)"). Rebuild after any site change. Both embed the
  footage (about 7 MB), so they are not kept in git. The demo runs the real
  scam rules and a JS port of the engines; `tests/test_demo_engine.py` fails if the port disagrees with the Python.
- **Installer:** `setup_jobboard.py` holds every tracked file. Regenerate it with `python make_installer.py` before each
  commit; `tests/test_installer.py` fails if it's out of date.
- **Tests:** `python -m pytest -q` (142 passing at handoff).

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

## Look and motion (Sept 30 redesign)

- **Landing pages are cinematic,** like the reference videos Evan sent: full-bleed footage and photos with huge
  condensed type over them, and the header floating clear over the footage until you scroll past.
  - **Student home:** a camera move along a brick walk, through a gothic arch under live oaks, into a sunlit quad.
    It is pinned and scrubbed by scroll (75 frames in `static/media/arch-*.webp`, drawn on a canvas by
    `static/fx.js`), with three captions that cross-fade: "Student jobs. Checked for scams." then "Scanned for scam
    signals." then "Then approved by a person." Then a photo chapter ("Offers come at night. So do scams."), the
    listing scanner, and a second photo chapter before the listings.
  - **Employer page:** a full-bleed office photo as the hero, three "what you get" tiles, the how-it-works bento, and a
    career-fair photo chapter.
  - Footage and photos were generated for this site with Higgsfield (Wan 3.0 video, Seedream and Z-Image stills,
    about 9.7 of Evan's 10 free credits). They show no real FSU buildings, people, logos or marks.
  - Reduced motion, Save-Data, slow connections and no-JS all get a still photo with the first caption and nothing
    pinned. Photos are served from `/static/media/` with a year-long cache; the page policy needed no change.
- **Type:** Archivo (variable, self-hosted in `static/fonts/`, OFL). Condensed uppercase for big statements
  (`.display`), normal width for body.
- **The listing scanner** (one effect, merging this chat's teardown with the `scan-hero` branch from another chat,
  commit 583902f): a fake listing on the student home ("Know it's real before you apply"). As you scroll, a gold
  line runs down it; each phrase the detector caught lights up (amber for warnings, red for critical) with a
  number, its flag slides in below, then a stamp lands and the verdict shows "Scam risk 100/100 from 8 signals".
  Scrolling back reverses it.
  - Nothing is hand-written: `ui.scan_findings()` runs `ui.SCAN_SAMPLE` through `msgcheck.check_listing`, the same
    code as the public scam check's listing tab, and the flag titles, stamp, verdict and advice are its output.
    `test_scanner_flags_come_from_the_detector` fails if any rule in `ui.SCAN_EXPECTED` stops firing on its phrase.
  - Driven by JS in `static/fx.js` (not the newer CSS scroll feature), so it works in every browser. Wide screens pin
    the section; phones let the copy scroll away and pin only the card and flags under the header; if even that
    won't fit it plays once when seen. No JS or reduced motion shows the finished state (tested).
  - Taken from the branch: detector verdict/advice, lasting highlights, middle-of-phrase triggers, phone pinning,
    live/static wording. Left out: Anton (Archivo stays), `static/scan.js` (folded into fx.js), `tools/make_installer.py`
    (root `make_installer.py` stays), `showcase.py` (ui.scan_findings does this and finds the underlines itself). The
    scan stays the second act; the cinematic arch footage stays the hero. The `scan-hero` branch can be deleted.
- **Signed-in pages** (all three roles, site and demo), kept quiet on purpose: nothing loops, numbers count up
  once, rings and bars draw in the first time they reach the screen.
  - Students: a dark welcome band with live listings, best fit and unread counts over a campus photo; fit badges
    with a small ring on job cards; the job page's fit ring, bars and checklist draw in; a campus photo as the
    profile cover.
  - Employers: welcome band with live listings, student views, candidates and unread; each listing's numbers are
    a funnel (a bar under each shows it as a share of students who viewed); a stage pipeline on the Candidates
    tab. The Messages tile on employer home was dropped since the band shows unread.
  - Reviewers: a "desk" header with every queue as a big count (replaces the small tabs), a scam-risk meter on
    each listing card, and J / K to move between cards.
  - Everywhere: "/" jumps to the page's search box. Reduced motion turns all of it off.
- **Other effects:** a light that follows the cursor around card borders, a slight cursor parallax on the hero
  footage, and one marquee of scam patterns.
- **Shared blocks:** `ui.cine_hero()`, `ui.students_chapters()`, `ui.employer_hero()`, `ui.employer_gets()`,
  `ui.employer_chapter()`, `ui.marquee_block()`, `ui.scan_block()`, `ui.how_students()`, `ui.how_employers()`
  feed both the site and the demo, so they can't drift. Links are passed in, so the demo points them at its router.
  The signed-in pieces (`ui.hello_band`, `ui.kpi`, `ui.fit_badge`, `ui.desk`, `ui.risk_meter`) have JS twins in
  `demo/app.js` with the same markup; change both.
- To swap the footage: replace the files in `static/media/` (same names; `ui.CINE_FRAMES` is the frame count).

## Decisions and why

- **Listings behind login:** "only verified FSU students see these" is the pitch to employers, and it keeps scrapers and
  scammers from copying real postings. Cost: no search traffic to job pages, which is fine for a campus-only board.
- **Scam check stays public but tiered:** it's the best advertisement and a lead source for other schools; the public view
  is enough to spot a scam but not enough to tune one until it passes.
- **Trust score 100 = good; listing number is labelled "scam risk":** two opposite scales must never share a label.
- **Employer view counts are totals only:** employers never see which students viewed or clicked Apply. Students appear in
  a tracker only when they message, are invited, or are saved from matches.
- **"Let approved employers find me" is checked by default at setup** (site and demo), and students can uncheck it.
  Without it the employer side has almost no students to match. **Revisit if FSU buys or partners on it:** a university
  will likely want students to opt in, so switch the default to unchecked then.
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
