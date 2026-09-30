# NoleCareerShield: handoff (Sept 30, 2026)

Read this first in a new chat. The README has the full feature table and settings; this file is where things
stand, what was decided and why, and what's next.

## Where everything lives

- **Code:** github.com/evannwilsonn/nolecareershield (branch `main`). Python / FastAPI / SQLite, deployed on Render (`render.yaml`, `DEPLOY.md`).
- **Demo:** the bar at the top has Explore as Student / Employer / Reviewer. `python demo/build.py` writes `demo/index.html` (full page) and `demo/NoleCareerShield_Demo.html` (body only,
  published as the Claude artifact "NoleCareerShield Demo (Copy)"). Rebuild after any site change. Both embed the
  footage (about 7 MB), so they are not kept in git. The demo runs the real
  scam rules and a JS port of the engines; `tests/test_demo_engine.py` fails if the port disagrees with the Python.
  The demo also has quick apply (Garnet's Social Media Intern takes applications) and the network (five sample students,
  one incoming request for Jordan), mirrored from `easyapply.py` and `network.py`; change both sides together.
- **Installer:** `setup_jobboard.py` holds every tracked file. Regenerate it with `python make_installer.py` before each
  commit; `tests/test_installer.py` fails if it's out of date.
- **Tests:** `python -m pytest -q` (143 passing at handoff).

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
- **Quick apply (`easyapply.py`):** an employer ticks "Collect applications on NoleCareerShield" on the post form and writes up
  to 5 questions (short / long / yes-no, optional or required). Questions can't ask for SSN, bank or card details,
  passwords or ID numbers (regex in `easyapply._BANNED`), and the question text is added to what the scam scanner reads.
  Students get a form filled from their profile (`/job/{id}/easy`), see what the employer will get before sending (name,
  major, graduation term, links, answers, note, resume only if ticked, never email), and can withdraw
  (`/applications`). The application lands in the employer's candidate tracker as **Applied**, with the answers in a
  collapsible block. Applying opens that student's profile to that employer only and allows them to message (even if the
  student is hidden from employers). Only approved employers can take easy-apply applications. 40 applications a day per
  student. Tables: `applications` (+ `jobs.easy_apply`, `jobs.questions`).
- **Network (`network.py`):** students connect with students (request with optional 200-char note, accept / decline,
  remove; a declined request can't be re-sent; 50 pending max; the note goes through the msgcheck scam scan and is not
  sent if the band is block or review). Connections show as counts and mutuals on profiles and power "People you may
  know" (same major +3, class year +2, shared skills up to +3, mutual connections +2 each). **There is no student to
  student messaging** (a deliberate call: no new inbox for strangers). Students can switch requests and discovery off
  (`allow_connections`, setup step 3). Students also follow approved employers; the jobs page has a "Companies I follow"
  filter; employers see a follower count, never who. Tables: `connections`, `follows`. Nav: Network (badge of incoming
  requests) and Applications for students.
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
    signals." then "Then approved by a professional." Then a photo chapter ("Not every offer is what it seems."), the employer chapter "Meet employers vetted by a professional.", the
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
  number, and its flag appears in the list below the card; then the stamp lands flat and the verdict shows "Scam
  risk 100/100 from 8 signals". Scrolling back reverses it. A break-apart effect (from the old teardown) was tried
  on the card and then on the flags, and taken out on Evan's call: it read as tacky and made the card harder to read.
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
    each listing card, and J / K to move between cards. The meter is a 0-100 gauge in four
    sections, Evan's cutoffs: green 0-25, yellow 26-50, orange 51-75, red 76-100, each shading darker toward its top.
    The marker sits at the listing's scam score and the score shows beside it. Aggregators (scam score 0 by design)
    sit at 60, labelled "Aggregator". `ui.risk_position` decides the spot; `demo/app.js` has a twin.
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
- **Quick apply shares only what the student sees on the form,** and only with the employer they apply to; withdrawing
  deletes the answers. Nothing changes for students who keep using external Apply links.
- **Connections without messages:** the site's safety pitch is that strangers can't reach students freely, so connecting
  is a mutual link plus counts, not an inbox. Add student messaging only with the same scan-and-report rules as employer
  messaging.
- **"Let approved employers find me" is checked by default at setup** (site and demo), and students can uncheck it.
  Without it the employer side has almost no students to match. **Revisit if FSU buys or partners on it:** a university
  will likely want students to opt in, so switch the default to unchecked then.
- **Demo never imitates FSU's sign-in page;** it shows a labelled stand-in, because a copy of a university login is what
  phishing looks like.
- **An "applicant tracker" that scores students on reply speed was dropped** (Evan's call after discussing privacy and
  hiring-law concerns).

## Scam detector: model and learning loop (Sept 30)

- **The learned model:** `scam_detector/ml.py`, trained by `scam_detector/tools/train_model.py`, documented in
  `scam_detector/MODEL.md`. It only escalates (flags a listing for review, or "Be careful" on the public listing
  check) and never rejects anything.
- **The learning loop:** `learning.py`.
  - `/admin/checks` is the label queue, with scam waves and label-all.
  - `/admin/model` shows the active model, the training runs and a "Retrain now" button.
  - It retrains monthly on the reviewers' confirmed labels and ships only through the gate.
- **Server requirement:** it needs scikit-learn on the server (in requirements.txt). The live model is saved
  next to the database on the Render disk.

## Scam detector: beyond wording (Sept 30)

Scammers rewrite their messages; these catch what they can't easily change. Everything only makes a verdict stricter.
- **Contact-detail memory (`defense.py`):** phones, emails, domains, Telegram handles, Cash App tags and crypto wallets
  from every sent-in check and board listing are stored as keyed hashes (`INDICATOR_KEY`, else derived from
  `SECRET_KEY`). Once a reviewer confirms a scam, any check reusing one of those details gets "Uses contact details
  from confirmed scams". Reports that share details are joined into rings on the label queue and `/admin/intel`.
- **Copies of real listings:** approved listings carry an invisible fingerprint in their description. A pasted copy
  with swapped contact details is "A copy of a real listing with different contact details".
- **Outside intel (`scam_detector/intel/`):** look-alike domains of FSU and approved employers, domain age, missing
  SPF/DMARC, shortened links (expanded), and URLhaus/Spamhaus/Chainabuse/Twilio when their keys are set. Network
  lookups run only with `INTEL_NETWORK=1` (on by default when `ENV=production`). A daily job watches certificate
  logs for new FSU look-alike domains.
- **The scam check:** a third tab, "A conversation", reads a whole pasted thread and shows which step of a known
  script it's at and what usually comes next (`scam_detector/conversation.py`). The message tab takes an
  attachment (offer-letter PDF, check photo, QR screenshot; `scam_detector/artifacts.py`). Every result lists
  "What they're asking you to do" (`scam_detector/asks.py`) and, when risky, where to report it. During the scam
  calendar's windows the check shows a notice.
- **`/admin/intel`:** drift alerts (confirmed scams the rules missed, waves the rules call safe, rising AI-only or
  ask-only catches, model uncertainty), repeated contact details (masked), rings, look-alike domains, the calendar
  editor and which outside checks are on.
- **Forward-by-email:** point a mail provider's inbound parse (SendGrid/Mailgun) at
  `/inbound/email?token=<INBOUND_EMAIL_TOKEN>`. The student gets the verdict by email; the message is kept for
  reviewers without their address.
- **Partner schools:** `/api/indicators` (header `X-Share-Key: <SHARE_FEED_KEY>`) serves confirmed-scam details as
  HMAC hashes under `SHARE_HMAC_KEY`, which partners must share. `PEER_FEEDS` pulls theirs daily.
- **Decoy desk (`/admin/decoys`):** off unless `DECOY_ENABLED=1`, which needs FSU legal sign-off first. Text-only
  invented personas; a reviewer pastes the conversation in, nothing is ever sent from the site, money is never
  moved. The scammer's messages go into the label queue.
- **Red team:** `python -m scam_detector.tools.redteam [--ai]` rewrites holdout scams to dodge filters and writes
  `models/REDTEAM_REPORT.md`. The variants are never trained on. First run: dollar amounts removed and "every 7
  days" instead of "weekly" slip past rules that catch the original.
- **Model uncertainty:** the model now carries class-conditional conformal values; "uncertain" cases go first in
  the label queue.

## Next / waiting on someone

1. **FSU single sign-on:** ask FSU ITS to register NoleCareerShield in FSU's Microsoft Entra tenant with redirect URI
   `https://<site>/sso/callback`, then set `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` on Render.
2. Decide whether students keep the three privacy toggles (visible to employers, share resume, allow messages).
3. Optional: `ANTHROPIC_API_KEY` on Render turns on AI for the assistant, resume tools and the scam check's second opinion.
4. Ideas raised but not built: student-to-student messages, employer "requests to connect", a followers-only feed,
   email digests for new listings from followed companies, a "usually replies within a day" badge; applicant-fraud flags for employers (fake or
   duplicate student accounts).

## Round: Handshake/LinkedIn/Indeed-style redesign (Sep 30)
- **Gauge:** every card shows "Scam risk N · status" (aggregators show 60, no "aggregator" label). Muted palette in ui.py `.risk`.
- **Qualifications + % match:** `quals.py` (employer-chosen skill/major/cert/standing/gradyear/gpa, required or preferred, max 10, protected-term blocklist) stored in `jobs.requirements`; merged into `fit.fit_score`, which now also returns `percent`, `level` (high ≥75 / medium ≥50 / low), `met`, `total`, and `must` on checklist items. Ported in demo/engine.js (parity test covers a job with requirements). No "top applicant" wording anywhere; numbers only.
- **Job board:** `jobboard.py` — two-pane list/detail (`/jobs?job=ID`), tabs Jobs/Saved/Resume optimizer, search + chips (incl. Quick apply filter), `saved_jobs` table, match panel, "What they're looking for", "Meet the poster" block. Styles in `css_jobs.py`.
- **Feed:** tabs Feed/For you/Saved, pills All/Your major/Employers, bookmarks (`post_saves`), right rail. Styles in `css_feed.py`.
- **Resume studio:** optimizer landing, ATS readiness report with accept/dismiss cards, tailor-to-a-job coverage. Styles in `css_resume.py`.
- **Career assistant** (was Job assistant): Indeed-Scout-style home, saved chats (`assistant_chats`/`assistant_msgs`), `/assistant/c/{id}`, job cards only from live approved listings. Styles in `css_assist.py`.
- **Naming:** the one-step apply feature is "Quick apply" in all user-visible text (DB columns still `easy_apply`). Listings with it show the note recommending applying on company sites.
- **Direct employers only:** post form requires "I work directly for this company"; recruiter/staffing language (`app._RECRUITER`) and a company name that doesn't match the employer's own (`app.company_mismatch`) are rejected.
- **Poster:** `jobs.poster_name/poster_title/show_email`; listing shows who posted; students can message them after applying (Quick apply or external Apply click); email shown only if the poster opts in.
- **Emails:** `emails.py` keeps an in-site copy (`emails` table, `/emails`, nav badge) of every email sent to a verified account; one-time sign-in links are redacted. Hooked via `mailer.copy_hook`.
- **Connections on profiles:** `network.connections_section` on own profile and /u pages.
- **Employer side:** ranked matches and candidates show "NN% match" and "Meets N of M of your requirements" with ✓/⊘/? per item.
