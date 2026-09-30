"""Team accounts for employers: one company, several recruiters (teams.py)."""
import hashlib
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import PW, csrf_from  # noqa: E402
from test_network import _Shim, add_job, employer, login, net, student, ucsrf  # noqa: E402,F401
from test_app import make_verified  # noqa: E402


def _db(net):
    return closing(sqlite3.connect(net.app.DB_PATH))


def _invite(owner, email, role="recruiter"):
    return owner.post("/team/invite", data={"csrf": ucsrf(owner, "/team"), "email": email, "role": role})


def _token(net, email):
    mail = [m for m in net.mailer.outbox if m["to"] == email and "invited you to join" in m["subject"]][-1]
    return re.search(r"/team/join\?token=([\w-]+)", mail["body"]).group(1)


def _member(net, owner, email="dana@acme.example", name="Dana Whitfield", title="Recruiter", role="recruiter"):
    """Invite, sign up and join: returns (client, user id)."""
    net.mailer.outbox.clear()
    assert _invite(owner, email, role).status_code == 303
    tok = _token(net, email)
    c = net.client()
    uid = make_verified(_Shim(net), "employer", email)
    login(c, "employer", email)
    page = c.get(f"/team/join?token={tok}")
    assert page.status_code == 200 and "Accept and join" in page.text, page.text[:600]
    r = c.post("/team/join", data={"csrf": ucsrf(c, "/team/join?token=" + tok), "token": tok, "name": name, "title": title})
    assert r.status_code == 303 and r.headers["location"] == "/team?done=joined", r.text[:600]
    return c, uid


def test_invite_rules_email_and_redaction(net):
    owner, oid = employer(net)
    net.mailer.outbox.clear()
    # Free mail and other domains are refused; the company's own domain works.
    r = _invite(owner, "someone@gmail.com")
    assert r.status_code == 400 and "Personal email addresses" in r.text
    r = _invite(owner, "someone@other.example")
    assert r.status_code == 400 and "@acme.example" in r.text
    assert not net.mailer.outbox
    assert _invite(owner, "Dana@Acme.example", "admin").status_code == 303
    mail = net.mailer.outbox[-1]
    assert mail["to"] == "dana@acme.example" and "Acme Analytics" in mail["subject"] and "as an Admin" in mail["body"]
    raw = _token(net, "dana@acme.example")
    with _db(net) as db:
        row = db.execute("SELECT token_hash, role, expires_at FROM org_invites WHERE org_id = ?", (oid,)).fetchone()
    assert row[0] == hashlib.sha256(raw.encode()).hexdigest() and raw not in row[0]      # only the hash is kept
    assert row[1] == "admin" and 6.9 * 86400 < row[2] - time.time() <= 7 * 86400
    # The invitee has an account: the in-site copy of the email hides the one-time link.
    make_verified(_Shim(net), "employer", "rae@acme.example")
    assert _invite(owner, "rae@acme.example").status_code == 303
    with _db(net) as db:
        body = db.execute("SELECT body FROM emails e JOIN users u ON u.id = e.user_id WHERE u.email = 'rae@acme.example'").fetchone()[0]
    assert "/team/join" not in body and "token=" not in body and "one-time link" in body
    page = owner.get("/team").text
    assert "dana@acme.example" in page and "Pending" in page and "Resend" in page
    # Resend issues a new link (the old one stops working); revoke removes it.
    with _db(net) as db:
        iid = db.execute("SELECT id FROM org_invites WHERE email = 'dana@acme.example'").fetchone()[0]
    assert owner.post(f"/team/invite/{iid}/resend", data={"csrf": ucsrf(owner, "/team")}).status_code == 303
    assert _token(net, "dana@acme.example") != raw
    assert owner.post(f"/team/invite/{iid}/revoke", data={"csrf": ucsrf(owner, "/team")}).status_code == 303
    with _db(net) as db:
        assert not db.execute("SELECT 1 FROM org_invites WHERE id = ?", (iid,)).fetchone()


def test_join_checks_email_expiry_and_existing_company(net):
    owner, oid = employer(net)
    net.mailer.outbox.clear()
    _invite(owner, "dana@acme.example")
    tok = _token(net, "dana@acme.example")
    # Someone else signed in can't use it.
    other = net.client()
    make_verified(_Shim(net), "employer", "sam@acme.example")
    login(other, "employer", "sam@acme.example")
    page = other.get(f"/team/join?token={tok}")
    assert page.status_code == 403 and "This invite is for dana@acme.example" in page.text
    # Signed out: the link sends you to the employer log-in and back.
    anon = net.client()
    r = anon.get(f"/team/join?token={tok}")
    assert r.status_code in (302, 303) and r.headers["location"].startswith("/login/employer")
    # An employer that already runs its own company (it has listings) can't join.
    rival, rid = employer(net, "boss@acme.example", company="Acme Analytics")
    add_job(net, rid)
    _invite(owner, "boss@acme.example")
    tok2 = _token(net, "boss@acme.example")
    page = rival.get(f"/team/join?token={tok2}")
    assert page.status_code == 403 and "already runs its own company" in page.text
    # Expired invites don't work.
    with _db(net) as db:
        db.execute("UPDATE org_invites SET expires_at = ? WHERE email = 'dana@acme.example'", (time.time() - 1,))
        db.commit()
    d = net.client()
    make_verified(_Shim(net), "employer", "dana@acme.example")
    login(d, "employer", "dana@acme.example")
    assert "expired" in d.get(f"/team/join?token={tok}").text


def test_member_acts_for_the_company(net):
    owner, oid = employer(net)
    s, sid = student(net)
    job = add_job(net, oid)
    dana, did = _member(net, owner)
    with _db(net) as db:
        assert db.execute("SELECT org_id, role, name, title FROM org_members WHERE user_id = ?", (did,)).fetchone() == (oid, "recruiter", "Dana Whitfield", "Recruiter")
        assert not db.execute("SELECT 1 FROM employer_profiles WHERE user_id = ?", (did,)).fetchone()     # no stray company of her own
    # Approval comes from the company: she can use the directory and sees the company's listings.
    assert "Find students" in dana.get("/talent").text and "opens once a reviewer approves" not in dana.get("/talent").text
    assert "Data Analyst Intern" in dana.get("/hiring").text
    assert dana.get(f"/hiring/{job}").status_code == 200
    # A listing she posts belongs to the company and names her.
    t = csrf_from(dana.get("/post").text)
    assert 'value="Dana Whitfield"' in dana.get("/post").text
    r = dana.post("/post", data={"csrf": t, "title": "Marketing Intern", "company": "Acme Analytics", "category": "Marketing", "work_type": "hybrid",
                                 "location": "Tallahassee, FL", "description": "Help our marketing team plan campus events and write posts. Paid $16/hour, 12 hours a week.",
                                 "apply_url": "https://acme.example/careers/marketing", "direct": "1", "show_email": "1"})
    assert r.status_code == 200, r.text[:400]
    with _db(net) as db:
        j = db.execute("SELECT id, employer_id, poster_name, poster_title, posted_by FROM jobs WHERE title = 'Marketing Intern'").fetchone()
    assert j[1:] == (oid, "Dana Whitfield", "Recruiter", did)
    net.app.set_review(j[0], "approved", "legit")
    assert "Marketing Intern" in owner.get("/hiring").text                      # the owner manages it too
    jp = s.get(f"/job/{j[0]}").text
    assert "Dana Whitfield" in jp and "dana@acme.example" in jp                   # her email, not the owner's
    # The student writes to the company; Dana reads and replies; the thread names her.
    r = s.post("/messages/new", data={"csrf": ucsrf(s), "to": oid, "job": job, "body": "Hi! Is the data internship still open for spring?"})
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    with _db(net) as db:
        assert db.execute("SELECT employer_id FROM conversations WHERE id = ?", (cid,)).fetchone()[0] == oid
    assert 'aria-label="1 unread"' in dana.get("/hiring").text
    assert "Is the data internship still open" in dana.get(f"/messages/{cid}").text
    r = dana.post(f"/messages/{cid}/send", data={"csrf": ucsrf(dana, f"/messages/{cid}"), "body": "Yes it is. Could you tell me about your SQL experience?"})
    assert r.status_code == 303
    with _db(net) as db:
        assert db.execute("SELECT sender_id FROM messages WHERE conversation_id = ? ORDER BY id DESC", (cid,)).fetchone()[0] == did
    sv = s.get(f"/messages/{cid}").text
    assert '<span class="sender">Dana Whitfield · Acme Analytics</span>' in sv
    ov = owner.get(f"/messages/{cid}").text
    assert "Dana Whitfield · Acme Analytics" in ov and 'class="bubble me' in ov                  # on the company's side for the owner too
    # A student who writes to Dana's own account id reaches the company.
    assert f'name="to" value="{oid}"' in s.get(f"/messages/new?to={did}").text
    # She manages candidates and schedules interviews.
    r = dana.post(f"/hiring/{job}/stage", data={"csrf": ucsrf(dana, "/hiring"), "student": sid, "stage": "interviewing", "note": "Strong SQL"})
    with _db(net) as db:
        assert db.execute("SELECT stage FROM candidates WHERE job_id = ? AND student_id = ?", (job, sid)).fetchone()[0] == "interviewing"
    assert "Propose interview times" in dana.get(f"/messages/{cid}").text
    # The company page lists the team to signed-in viewers; her id leads to the company.
    cp = s.get(f"/company/{oid}").text
    assert "<h2>Team</h2>" in cp and "Dana Whitfield" in cp and "Pat Lee" in cp
    assert s.get(f"/company/{did}").headers["location"] == f"/company/{oid}"
    # Templates are shared by the team.
    assert "Message templates" in dana.get("/messages/templates").text
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM message_templates WHERE employer_id = ?", (did,)).fetchone()[0] == 0


def test_roles_permissions_and_removal(net):
    owner, oid = employer(net)
    dana, did = _member(net, owner)
    nav = dana.get("/team").text
    assert 'href="/team"' in nav and "Your role: Recruiter" in nav and "Invite a teammate" not in nav
    # Recruiters can't manage the team or edit the company profile.
    assert _invite(dana, "x@acme.example").status_code == 403
    assert dana.get("/profile/setup/1").status_code == 403
    assert dana.post("/profile/setup/1", data={"csrf": ucsrf(dana), "company": "Evil"}).status_code == 403
    assert "Edit profile" not in dana.get("/profile").text
    # The owner makes her an admin: now she can invite and edit the profile.
    assert owner.post(f"/team/member/{did}/role", data={"csrf": ucsrf(owner, "/team"), "role": "admin"}).status_code == 303
    assert dana.get("/profile/setup/1").status_code == 200
    assert _invite(dana, "lee@acme.example").status_code == 303
    # Nobody can demote or remove the owner.
    dana.post(f"/team/member/{oid}/role", data={"csrf": ucsrf(dana, "/team"), "role": "recruiter"})
    dana.post(f"/team/member/{oid}/remove", data={"csrf": ucsrf(dana, "/team")})
    with _db(net) as db:
        assert db.execute("SELECT role FROM org_members WHERE user_id = ?", (oid,)).fetchone()[0] == "owner"
    # Removing her ends her access to company data.
    assert owner.post(f"/team/member/{did}/remove", data={"csrf": ucsrf(owner, "/team")}).status_code == 303
    with _db(net) as db:
        assert not db.execute("SELECT 1 FROM org_members WHERE user_id = ?", (did,)).fetchone()
    assert "Data Analyst" not in dana.get("/hiring").text


def test_delete_export_and_transfer(net):
    owner, oid = employer(net)
    s, sid = student(net)
    add_job(net, oid)
    dana, did = _member(net, owner)
    # Export: membership for her, the team and invites for the owner (never the token).
    mine = json.loads(dana.get("/profile/export").text)
    assert mine["team_membership"]["org_id"] == oid and mine["team_membership"]["company"] == "Acme Analytics"
    _invite(owner, "lee@acme.example")
    full = json.loads(owner.get("/profile/export").text)
    assert {m["email"] for m in full["team"]} == {"recruiter@acme.example", "dana@acme.example"}
    assert full["team_invites"][0]["email"] == "lee@acme.example" and "token_hash" not in full["team_invites"][0]
    # The owner can't delete the account while others are on the team.
    r = owner.post("/profile/delete", data={"csrf": ucsrf(owner, "/profile"), "password": PW})
    assert r.status_code == 409 and "Transfer ownership" in r.text
    # Transfer: the company moves to Dana's id; the old owner stays as an admin.
    assert owner.post("/team/transfer", data={"csrf": ucsrf(owner, "/team"), "to": did}).status_code == 303
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE employer_id = ?", (did,)).fetchone()[0] == 1
        assert db.execute("SELECT company FROM employer_profiles WHERE user_id = ?", (did,)).fetchone()[0] == "Acme Analytics"
        assert dict(db.execute("SELECT user_id, role FROM org_members WHERE org_id = ?", (did,)).fetchall()) == {did: "owner", oid: "admin"}
    assert "Data Analyst Intern" in owner.get("/hiring").text
    # Now the old owner can delete: only the membership goes, the company stays.
    r = owner.post("/profile/delete", data={"csrf": ucsrf(owner, "/profile"), "password": PW})
    assert r.status_code == 200
    with _db(net) as db:
        assert db.execute("SELECT status FROM employer_profiles WHERE user_id = ?", (did,)).fetchone()[0] == "approved"
        assert db.execute("SELECT COUNT(*) FROM org_members WHERE org_id = ?", (did,)).fetchone()[0] == 1
    assert "Data Analyst Intern" in dana.get("/hiring").text


def test_member_delete_blanks_messages_keeps_company(net):
    owner, oid = employer(net)
    s, sid = student(net)
    dana, did = _member(net, owner)
    r = dana.post("/messages/new", data={"csrf": ucsrf(dana), "to": sid, "body": "Hi Jordan, we'd love to tell you about our analytics internship."})
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    assert dana.post("/profile/delete", data={"csrf": ucsrf(dana, "/profile"), "password": PW}).status_code == 200
    with _db(net) as db:
        assert db.execute("SELECT body, status FROM messages WHERE conversation_id = ?", (cid,)).fetchone() == ("", "removed")
        assert db.execute("SELECT employer_id, blocked_by FROM conversations WHERE id = ?", (cid,)).fetchone() == (oid, None)
        assert db.execute("SELECT status FROM employer_profiles WHERE user_id = ?", (oid,)).fetchone()[0] == "approved"
    assert "Message removed" in owner.get(f"/messages/{cid}").text


def test_org_helpers_default_to_self(net):
    import store
    with store.db() as conn:
        assert store.org_of(conn, 12345) == 12345 and store.org_role(conn, 12345) == "owner"
    assert store.org_id({"id": 7}) == 7 and store.org_id({"id": 7, "org_id": 3}) == 3
