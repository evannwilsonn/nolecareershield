# Nole Verified Jobs

A curated job board for FSU students. Every listing is **scam-scanned and then
reviewed by a human** before it appears — only vetted postings go live.

Built on the [`job-scam-detector`](../job-scam-detector) engine.

## The model: open to browse, approval-gated to publish

- **Anyone can browse** — no login, no account, no data collected from students.
- **Anyone can submit** a listing — but submitting is not publishing.
- **Every submission is scored** by the scam detector, then **waits in a review
  queue** until an admin approves it. Nothing is public until a human approves.

This gives "vetted employers only" exclusivity **without** authenticating anyone
or storing student identity data — which is the legally clean way to be
selective. Gating by *who someone is* (verifying FSU affiliation) would require
tying into the university's login system or collecting student data (a FERPA/
privacy problem). Gating by *editorial review of each listing* achieves the same
goal with none of that exposure.

## Privacy by design

No student accounts, no logins for job seekers, no resumes, no job-seeker data
of any kind. Storage holds only what an employer types into the post form plus
the scam score and review status. No analytics, no trackers, no cookies, no
third-party scripts. The only outbound network call is optional RDAP/DNS
enrichment, **off by default** on submission. The `contact` field is shown
publicly (only if approved) and is optional; the form warns the poster.

## Admin / review queue

The review queue at `/admin` is protected by a single password read from the
`ADMIN_PASSWORD` environment variable.

**Set a real password before deploying** — the default is `changeme`.

```bash
export ADMIN_PASSWORD=your-strong-secret   # Windows: set ADMIN_PASSWORD=...
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000 (public) and http://127.0.0.1:8000/admin
(review queue — sign in, approve or reject each submission).

## Run locally

```bash
pip install -r requirements.txt
export ADMIN_PASSWORD=your-strong-secret
uvicorn app:app --reload
```

Storage is SQLite (`jobs.db`), created automatically. Delete it to reset.

## Deploy (GitHub -> Render / Railway)

Code lives on GitHub. To make it a live site, deploy from the repo to a Python
host (Render, Railway, Fly.io):

- Build:  `pip install -r requirements.txt`
- Start:  `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Set the `ADMIN_PASSWORD` environment variable in the host's dashboard.
- For listings to persist across restarts, attach a small disk/volume for
  `jobs.db`, or move to the host's managed Postgres when you outgrow SQLite.

Wix / static hosts won't work — this app needs a Python backend to run the
scorer and the review queue.

## Trademark note

Uses an original emblem and the garnet/gold color family only. It does **not**
use FSU's official seal or logos, and the footer states the project is
independent and unaffiliated. Add official marks only with university permission.

## Not built (on purpose)

Student accounts, messaging, applicant tracking, and FSU-identity verification
are deliberately absent — each would collect personal data and add privacy/legal
obligations. Add them only as explicit, documented decisions if real demand
appears.
