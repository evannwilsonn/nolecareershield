"""The Handshake-style feed: tabs, pill filters, For you ranking, bookmark saves, the right rail."""
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_network import SCAMS, admin, admin_csrf, employer, net, student, ucsrf  # noqa: E402,F401


def set_major(n, uid, major, skills=None):
    with closing(sqlite3.connect(n.app.DB_PATH)) as db:
        db.execute("UPDATE student_profiles SET major = ? WHERE user_id = ?", (major, uid))
        if skills is not None:
            import json
            db.execute("UPDATE student_profiles SET skills = ? WHERE user_id = ?", (json.dumps(skills), uid))
        db.commit()


def post(c, body, kind="question"):
    r = c.post("/feed/post", data={"csrf": ucsrf(c), "kind": kind, "body": body})
    assert r.status_code == 303, r.text[:300]


def post_id(n, needle):
    with closing(sqlite3.connect(n.app.DB_PATH)) as db:
        return db.execute("SELECT id FROM posts WHERE body LIKE ?", (f"%{needle}%",)).fetchone()[0]


def publish_employer_post(n, emp, needle):
    a = admin(n)
    pid = post_id(n, needle)
    a.post(f"/admin/posts/{pid}/publish", data={"csrf": admin_csrf(a, "/admin/posts")})
    return pid


def test_layout_has_tabs_pills_composer_and_rail(net):
    s, sid = student(net)
    page = s.get("/feed").text
    for label in ("Feed", "For you", "Saved"):
        assert f">{label}</a>" in page
    assert 'aria-current=page>Feed' in page.replace('"', "")
    for pill in ("All", "Your major", "Employers"):
        assert pill in page
    assert "Share something with the community" in page
    assert 'name="body"' in page and "Community guidelines" in page
    assert ".fd-grid" in page                                                         # feed css is appended to the shared stylesheet


def test_save_unsave_and_saved_tab(net):
    s, sid = student(net)
    assert "No saved posts yet" in s.get("/feed?tab=saved").text
    post(s, "Has anyone done the Deloitte info session? Worth going as a sophomore?")
    pid = post_id(net, "Deloitte")
    page = s.get("/feed").text
    assert f"/feed/{pid}/save" in page and f"/feed/{pid}/unsave" not in page
    t = ucsrf(s)
    r = s.post(f"/feed/{pid}/save", data={"csrf": t, "next": "/feed?tab=foryou"})
    assert r.status_code == 303 and r.headers["location"] == "/feed?tab=foryou"
    s.post(f"/feed/{pid}/save", data={"csrf": t})                                   # saving twice keeps one row
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM post_saves WHERE user_id = ? AND post_id = ?", (sid, pid)).fetchone()[0] == 1
    assert f"/feed/{pid}/unsave" in s.get("/feed").text
    saved = s.get("/feed?tab=saved").text
    assert "Deloitte" in saved and "No saved posts yet" not in saved
    # Another student's saved list is their own.
    peer, _ = student(net, "peer@fsu.edu", "Peer P.")
    assert "Deloitte" not in peer.get("/feed?tab=saved").text and "No saved posts yet" in peer.get("/feed?tab=saved").text
    r = s.post(f"/feed/{pid}/unsave", data={"csrf": t, "next": "/feed?tab=saved"})
    assert r.status_code == 303 and r.headers["location"] == "/feed?tab=saved"
    assert "No saved posts yet" in s.get("/feed?tab=saved").text


def test_save_needs_csrf_and_safe_redirect(net):
    s, sid = student(net)
    post(s, "Question for the FSU crowd: how do you prepare for a case interview?")
    pid = post_id(net, "case interview")
    r = s.post(f"/feed/{pid}/save", data={"csrf": "wrong", "next": "/feed"})
    assert r.status_code == 303
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 0
    t = ucsrf(s)
    for bad in ("//evil.example", "https://evil.example/feed", "/feed/../../x", "/messages", "/feed\\evil"):
        r = s.post(f"/feed/{pid}/save", data={"csrf": t, "next": bad})
        assert r.headers["location"] == "/feed", bad
    assert net.client().post(f"/feed/{pid}/save", data={"csrf": t}).status_code in (303, 401, 403)   # logged out


def test_only_published_posts_can_be_saved_and_removed_ones_disappear(net):
    s, sid = student(net)
    t = ucsrf(s)
    post(s, SCAMS[1], "opportunity")
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        row = db.execute("SELECT id, status FROM posts").fetchone()
    assert row[1] != "published"
    s.post(f"/feed/{row[0]}/save", data={"csrf": t})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 0
    post(s, "Advice for FSU students: go to office hours in week one, it really helps.", "advice")
    pid = post_id(net, "office hours")
    peer, _ = student(net, "peer@fsu.edu", "Peer P.")
    peer.post(f"/feed/{pid}/save", data={"csrf": ucsrf(peer)})
    assert "office hours" in peer.get("/feed?tab=saved").text
    s.post(f"/feed/{pid}/delete", data={"csrf": t})                                  # author removes it
    assert "office hours" not in peer.get("/feed?tab=saved").text


def test_your_major_and_employers_pills(net):
    s, sid = student(net)                                                            # Statistics
    peer, pid_ = student(net, "peer@fsu.edu", "Peer P.")
    other, oid = student(net, "art@fsu.edu", "Art A.")
    set_major(net, oid, "Studio Art")
    post(s, "Statistics majors: which stats electives are worth taking this spring?")
    post(peer, "Anyone in my stats classes want to study for the exam together?")
    post(other, "Looking for a ceramics studio partner for the FSU art show this semester.")
    emp, eid = employer(net)
    emp.post("/feed/post", data={"csrf": ucsrf(emp), "kind": "info_session",
                                 "body": "Acme is hosting an info session for FSU students interested in summer data internships. Thursday 6pm at the Career Center."})
    publish_employer_post(net, emp, "Acme is hosting")
    everything = s.get("/feed").text
    assert "ceramics" in everything and "Acme is hosting" in everything
    major = s.get("/feed?f=major").text
    assert "stats electives" in major and "study for the exam" in major
    assert "ceramics" not in major and "Acme is hosting" not in major
    emps = s.get("/feed?f=employers").text
    assert "Acme is hosting" in emps and "ceramics" not in emps and "stats electives" not in emps
    assert 'aria-current=true' in emps.replace('"', "")
    # Art major sees only art posts under Your major; the pill filters For you too.
    assert "ceramics" in other.get("/feed?f=major").text and "stats electives" not in other.get("/feed?f=major").text
    assert "stats electives" not in s.get("/feed?tab=foryou&f=employers").text
    # Employers have no major pill and a bogus filter falls back to All.
    ep = emp.get("/feed?f=major").text
    assert "Your major" not in ep and "ceramics" in ep


def test_for_you_ranks_by_major_skills_and_recency(net):
    s, sid = student(net)                                                            # Statistics; Python, SQL, Excel, Tableau, R
    art, aid = student(net, "art@fsu.edu", "Art A.")
    set_major(net, aid, "Studio Art", ["Ceramics"])
    stat, tid = student(net, "stat@fsu.edu", "Stat S.")
    post(art, "Fun fact about Florida weather patterns in the fall semester, nothing else.")   # newest of the three below
    post(stat, "Peer tip for Statistics majors: office hours beat guessing every time.")
    post(art, "Brand new post about pottery glazes and kilns for anyone curious around campus.")
    page = s.get("/feed?tab=foryou").text
    order = [page.index("Statistics majors"), page.index("pottery glazes"), page.index("Florida weather")]
    assert order[0] < order[1] and order[0] < order[2]                               # same major beats newer off-topic posts
    # The scoring function itself: skills named in the body and a shared major both lift a post.
    import feed
    viewer = {"major": "Statistics", "skills": ["Python", "SQL"]}
    now = 1_000_000.0
    base = {"body": "Something unrelated to anything", "created_at": now}
    plain = feed.for_you_score(base, viewer, {"major": "Studio Art", "skills": []}, now)
    same_major = feed.for_you_score(base, viewer, {"major": "statistics", "skills": []}, now)
    skills = feed.for_you_score({**base, "body": "We use Python and SQL daily"}, viewer, {"major": "Studio Art", "skills": []}, now)
    old = feed.for_you_score({**base, "created_at": now - 30 * 86400}, viewer, {"major": "Studio Art", "skills": []}, now)
    assert same_major == plain + 4 and skills == plain + 2 and old < plain


def test_right_rail_suggestions_and_trending(net):
    s, sid = student(net)
    peer, pid_ = student(net, "peer@fsu.edu", "Peer Person")
    post(s, "Anyone using tableau for the analytics capstone this term?")
    post(peer, "Tableau tutorials worth watching before the capstone begins?")
    page = s.get("/feed").text
    assert "Peer Person" in page and "/network/connect" in page                       # suggested person with a Connect button
    assert "Trending topics" in page and "tableau" in page.lower()
    assert "/feed?q=tableau" in page
    hits = s.get("/feed?q=tableau").text
    assert "analytics capstone" in hits and "Topic: tableau" in hits
    assert s.get("/feed?q=%25%27%22").status_code == 200


def test_pagination_keeps_filters(net):
    s, sid = student(net)
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        for i in range(23):
            db.execute("INSERT INTO posts (author_id, kind, body, status, created_at) VALUES (?,?,?,?,?)",
                       (sid, "question", f"Question number {i:02d} for FSU students about resumes and internships.", "published", 1000.0 + i))
        db.commit()
    page = s.get("/feed").text
    assert "Older posts" in page and "Question number 22" in page and "Question number 00" not in page
    nxt = re.search(r'href="(/feed\?[^"]*before=\d+)"', page).group(1)
    assert "Question number 00" in s.get(nxt.replace("&amp;", "&")).text
    filtered = s.get("/feed?f=major").text
    assert "before=" in filtered and "f=major&amp;before=" in filtered


def test_saves_are_in_export_and_deleted_with_the_account(net):
    s, sid = student(net)
    peer, peer_id = student(net, "peer@fsu.edu", "Peer P.")
    post(peer, "Advice for FSU students: apply early to summer internships, seriously.", "advice")
    pid = post_id(net, "apply early")
    t = ucsrf(s)
    s.post(f"/feed/{pid}/save", data={"csrf": t})
    assert '"saved_posts"' in s.get("/profile/export").text and f'"post_id": {pid}' in s.get("/profile/export").text
    peer.post(f"/feed/{pid}/save", data={"csrf": ucsrf(peer)})
    # Deleting the saver clears their rows only; deleting the author clears everyone's saves of that post.
    import store
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 2
        store.delete_account(db, sid)
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 1
        store.delete_account(db, peer_id)
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 0


def test_purge_drops_saves_of_posts_that_are_gone(net):
    s, sid = student(net)
    import store
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("INSERT INTO post_saves (user_id, post_id, created_at) VALUES (?,?,0)", (sid, 9999))
        store.purge(db)
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 0


def test_visitors_and_unapproved_employers_get_no_posts_or_saves(net):
    v = net.client()
    assert v.get("/feed?tab=saved").status_code == 200 and "No saved posts yet" not in v.get("/feed?tab=saved").text
    s, sid = student(net)
    post(s, "Question for FSU students: best campus coffee spot for group study sessions?")
    pid = post_id(net, "coffee spot")
    pend, _ = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    pend.post(f"/feed/{pid}/save", data={"csrf": ucsrf(pend)})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM post_saves").fetchone()[0] == 0
