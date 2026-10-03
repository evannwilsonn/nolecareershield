"""Dynamic cross-site-scripting sweep.

Seeds tagged payloads into every user-controllable text field reachable through the real forms and JSON APIs (as a
visitor, student, employer, team member and admin), then crawls every GET route as every kind of user (plus a pass
that puts payloads in the query string) and scans each HTML response, each POST response, and every HTML fragment
returned by the JSON APIs. A hit is reported only when a payload comes out in executable form:

  * an injected element:            <x-xss-NNN>                (raw, anywhere in the page)
  * a quote breakout into a tag:    " data-xss-NNN="1  /  ' data-xss-NNN='1   (seen by an HTML parser as a real attribute)
  * a script URL in a link/source:  href="javascript:alert(NNN)" / src=... / action=...

Escaped output (&lt;x-xss, &quot;, &#x27;) is fine and is not reported. The test collects every hit first and then fails
with one readable list (marker -> field -> page -> snippet).  Run:
    python -m pytest -q -p no:cacheprovider -W ignore tests/test_xss_sweep.py -s
"""
import itertools, json, re, sqlite3, sys, time
from collections import defaultdict
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import PW, csrf_from, make_verified  # noqa: E402,F401
from test_network import RESUME, _Shim, add_job, admin, admin_csrf, employer, login, net, student, ucsrf  # noqa: E402,F401


# ---------------------------------------------------------------- payloads

class Payloads:
    def __init__(self):
        self.n = 100
        self.label: dict[str, str] = {}          # tag -> "feature: field"

    def _tag(self, label):
        self.n += 1
        t = str(self.n)
        self.label[t] = label
        return t

    def text(self, label, limit=None, prefix=""):
        """Element + double-quote + single-quote breakout in one value (falls back to the element alone when short)."""
        t = self._tag(label)
        full = f'{prefix}<x-xss-{t}>" data-xss-{t}="1\' data-xss-{t}=\'1'
        if limit and len(full) > limit:
            full = f'{prefix}<x-xss-{t}>'
            if len(full) > limit:
                full = f'<x-xss-{t}>'
        return full

    def quote(self, label):
        """Quote breakouts only, for fields that refuse angle brackets."""
        t = self._tag(label)
        return f'" data-xss-{t}="1\' data-xss-{t}=\'1'

    def url(self, label):
        t = self._tag(label)
        return f"javascript:alert({t})"

    def urlq(self, label):
        """A web address that tries to break out of an href attribute."""
        t = self._tag(label)
        return f'https://example.com/?a="><x-xss-{t}>" data-xss-{t}="1'


# ---------------------------------------------------------------- detection

_URL_ATTRS = {"href", "src", "action", "formaction", "xlink:href", "data", "poster", "srcdoc", "background", "cite"}


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hits = []

    def handle_starttag(self, tag, attrs):
        if tag.startswith("x-xss-"):
            self.hits.append((tag[6:], f"element <{tag}>"))
        for k, v in attrs:
            k = (k or "").lower()
            if k.startswith("data-xss-"):
                self.hits.append((k[9:].strip("'\""), f"attribute breakout ({k}) in <{tag}>"))
            if k in _URL_ATTRS and v and re.sub(r"[\s\x00-\x1f]", "", v).lower().startswith("javascript:"):
                m = re.search(r"alert\((\d+)\)", v)
                self.hits.append((m.group(1) if m else "?", f'{k}="javascript:..." on <{tag}>'))

    handle_startendtag = handle_starttag


def _snip(html, tag):
    for pat in (f"<x-xss-{tag}", f"data-xss-{tag}", f"alert({tag})"):
        for m in re.finditer(re.escape(pat), html):
            s = html[max(0, m.start() - 60): m.start() + 60]
            if "&lt;x-xss" in s and pat.startswith("<"):
                continue
            return s.replace("\n", " ")
    return ""


def scan_html(html: str) -> list[tuple[str, str, str]]:
    out, seen = [], set()
    p = _Scan()
    try:
        p.feed(html)
        p.close()
    except Exception:                                     # noqa: BLE001 - a parser hiccup must not hide raw hits
        pass
    for tag, kind in p.hits:
        if (tag, kind) not in seen:
            seen.add((tag, kind))
            out.append((tag, kind, _snip(html, tag)))
    # Raw element anywhere (also inside <script>/<textarea>/<title>, which the parser treats as text).
    for m in re.finditer(r"<x-xss-(\d+)", html):
        tag = m.group(1)
        if not any(t == tag and k.startswith("element") for t, k in seen):
            seen.add((tag, "element"))
            before = html[:m.start()].lower()
            ctxt = max(("title", "textarea", "script", "style", "!--"), key=lambda t: before.rfind("<" + t))
            ctxt = ctxt if before.rfind("<" + ctxt) > before.rfind("</" + ctxt.strip("!-")) else "raw text"
            out.append((tag, f"raw <x-xss-…> inside <{ctxt}> (RCDATA/raw text: a closing tag in the value breaks out)",
                        html[max(0, m.start() - 60): m.start() + 60].replace("\n", " ")))
    return out


# ---------------------------------------------------------------- the sweep

class Sweep:
    def __init__(self, n):
        self.n = n
        self.P = Payloads()
        self.seeded = defaultdict(list)          # feature -> [field]
        self.rejected = []                       # (feature, field(s), status, reason)
        self.skipped = []                        # (step, reason)
        self.hits = {}                           # (tag, kind, url) -> snippet
        self.pages = 0
        self.errors = {}
        self.seen = set()                        # markers observed in any response (escaped or not)                         # "METHOD url" -> first line of the server error (500s)
        self.scanned_json = 0
        self._since_reset = 0

    # -- plumbing
    def no_raise(self):
        """Server errors come back as 500 pages (recorded) instead of exceptions, so one crash doesn't hide a page."""
        for c in self.n.clients:
            t = getattr(c, "_transport", None)
            if t is not None and hasattr(t, "raise_server_exceptions"):
                t.raise_server_exceptions = False

    def reset_limits(self, force=False):
        self.no_raise()
        self._since_reset += 1
        if force or self._since_reset >= 15:
            self._since_reset = 0
            for lim in self.n.security.ALL_LIMITERS:
                try:
                    lim.reset_all()
                except Exception:                 # noqa: BLE001
                    pass

    def check(self, r, where):
        if r.status_code >= 500:
            self.errors.setdefault(where.split(" as ")[0][:160], f"{r.status_code} as {where.split(' as ')[-1]}")
        ct = r.headers.get("content-type", "")
        self.seen.update(re.findall(r"x-xss-(\d+)|data-xss-(\d+)|alert\((\d+)\)", r.text or "") and
                         {g for t in re.findall(r"x-xss-(\d+)|data-xss-(\d+)|alert\((\d+)\)", r.text or "") for g in t if g})
        if "text/html" in ct:
            self.pages += 1
            for tag, kind, snip in scan_html(r.text):
                self.hits.setdefault((tag, kind, where), snip)
        elif "json" in ct:
            try:
                data = r.json()
            except ValueError:
                return
            self.scanned_json += 1
            self._scan_json(data, where, "")

    def _scan_json(self, data, where, key):
        if isinstance(data, dict):
            for k, v in data.items():
                self._scan_json(v, where, str(k))
        elif isinstance(data, list):
            for v in data:
                self._scan_json(v, where, key)
        elif isinstance(data, str) and ("html" in key.lower() or key in ("ctx", "panel", "body_html")):
            for tag, kind, snip in scan_html(data):
                self.hits.setdefault((tag, kind, f"{where} [json:{key}]"), snip)

    def get(self, c, url, who):
        self.reset_limits()
        try:
            r = c.get(url)
        except Exception as e:                    # noqa: BLE001
            self.skipped.append((f"GET {url} as {who}", f"raised {e!r}"[:200]))
            return None
        self.check(r, f"GET {url} as {who}")
        return r

    def post(self, c, url, feature, fields, ok=(200, 303), who="", **kw):
        """POST a form/JSON; scan the response; record the fields as seeded (or rejected, with the reason)."""
        self.reset_limits()
        try:
            r = c.post(url, **kw)
        except Exception as e:                    # noqa: BLE001
            self.skipped.append((f"{feature}: POST {url}", f"raised {e!r}"[:200]))
            return None
        self.check(r, f"POST {url}" + (f" as {who}" if who else ""))
        if r.status_code in ok and not _looks_failed(r):
            self.seeded[feature].extend(fields)
        else:
            self.rejected.append((feature, ", ".join(fields), r.status_code, _reason(r)))
        return r

    def step(self, name, fn):
        try:
            fn()
        except Exception as e:                    # noqa: BLE001 - one broken feature must not stop the sweep
            self.skipped.append((name, f"{type(e).__name__}: {e}"[:300]))

    def db(self):
        return closing(sqlite3.connect(self.n.app.DB_PATH))

    def ids(self, sql, args=()):
        try:
            with self.db() as d:
                return [r[0] for r in d.execute(sql, args).fetchall()]
        except sqlite3.Error as e:
            self.skipped.append((f"sql {sql[:60]}", str(e)))
            return []


def _looks_failed(r):
    if r.status_code == 303:
        return bool(re.search(r"refused|error=|err=", r.headers.get("location", "")))
    try:
        if "json" in r.headers.get("content-type", "") and isinstance(r.json(), dict) and r.json().get("error"):
            return True
    except ValueError:
        pass
    return False


def _reason(r):
    try:
        if "json" in r.headers.get("content-type", ""):
            return str(r.json().get("error") or r.json().get("detail"))[:160]
    except (ValueError, AttributeError):
        pass
    m = re.findall(r'class="(?:banner|err|error)[^"]*"[^>]*>(.*?)</', r.text or "", re.S)
    txt = re.sub(r"<[^>]+>", "", " ".join(m)).strip() if m else ""
    return (txt or (r.text or "")[:120]).replace("\n", " ")[:160]


def _loc_id(r, pat):
    m = re.search(pat, r.headers.get("location", "") if r is not None else "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- the AI stand-in

def _fill_schema(schema, P, label):
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object" or "properties" in schema:
        return {k: _fill_schema(v, P, f"{label}.{k}") for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_fill_schema(schema.get("items") or {"type": "string"}, P, label)]
    if t in ("integer", "number"):
        return 1
    if t == "boolean":
        return True
    return P.text(f"AI output: {label}")


def _ai_handler(P):
    def handler(request):
        body = json.loads(request.content or b"{}")
        tools = body.get("tools") or []
        choice = body.get("tool_choice") or {}
        if tools and choice.get("type") in ("tool", "any"):
            tool = next((x for x in tools if x.get("name") == choice.get("name")), tools[0])
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t0", "name": tool["name"],
                                                          "input": _fill_schema(tool.get("input_schema") or {}, P, tool["name"])}],
                                             "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}})
        t1, t2 = P.text("AI output: free text"), P.url("AI output: markdown link")
        text = f"Here you go {t1}\n- [Open]({t2})\n- **{P.text('AI output: bold')}**"
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})
    return handler


# ---------------------------------------------------------------- seeding

def _day(days):
    import scheduling
    return scheduling.to_et(time.time() + days * 86400).date().isoformat()


def seed_all(S: Sweep, monkeypatch):
    n, P = S.n, S.P
    ctx = {}

    # ---- accounts
    s1, sid1 = student(n, "jordan@fsu.edu", "Jordan R.")
    s2, sid2 = student(n, "blair@fsu.edu", "Blair B.")
    emp, eid = employer(n)
    ctx.update(s1=s1, sid1=sid1, s2=s2, sid2=sid2, emp=emp, eid=eid)
    job_a = add_job(n, eid)
    ctx["job_a"] = job_a

    # ---- visitor forms (public scam check, sign-up / log-in reflections)
    def visitor():
        v = n.client()
        ctx["vis"] = v
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check", "public check", ["text", "sender"], data={"csrf": tok, "who": "",
               "text": "Hello, we reviewed your resume. " + P.text("check: text (visitor)"), "sender": P.text("check: sender (visitor)", 200)})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/thread", "public check", ["thread text", "me"], data={"csrf": tok,
               "text": "Recruiter: Hi there, send your bank details " + P.text("check/thread: text") + "\nMe: ok",
               "me": P.text("check/thread: me", 60)})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/school", "public check", ["school request"], data={"csrf": tok, "school": "University of " + P.text("check/school: school", 120)})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/school", "public check", ["school request (quotes only)"], data={"csrf": tok, "school": "University of Tampa " + P.quote("check/school: school (quotes)")})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/listing", "public check", ["listing title", "company", "description", "contact"], data={
               "csrf": tok, "title": "Remote Assistant " + P.text("check/listing: title", 200), "company": "Quick " + P.text("check/listing: company", 200),
               "description": "Work from home, earn $900 a week processing payments. " + P.text("check/listing: description"),
               "url": "", "contact": P.text("check/listing: contact", 200)})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/listing", "public check", ["listing url (javascript:)"], data={
               "csrf": tok, "title": "Remote Assistant", "company": "Quick Staffing",
               "description": "Work from home, earn $900 a week processing payments for our clients.", "url": P.url("check/listing: url"), "contact": ""})
        tok = csrf_from(v.get("/check").text)
        S.post(v, "/check/listing", "public check", ["listing url (quote breakout)"], data={
               "csrf": tok, "title": "Remote Assistant", "company": "Quick Staffing",
               "description": "Work from home, earn $900 a week processing payments for our clients.", "url": P.urlq("check/listing: url"), "contact": ""})
        for kind in ("message", "listing"):
            tok = csrf_from(v.get("/check").text)
            S.post(v, "/check/submit", "public check", [f"submit ({kind}): text, sender, title, company, url"], data={
                   "csrf": tok, "text": "Congratulations, you were selected. " + P.text(f"check/submit {kind}: text"),
                   "sender": P.text(f"check/submit {kind}: sender", 200), "band": "high", "label": "scam", "kind": kind,
                   "title": P.text(f"check/submit {kind}: title", 200), "company": P.text(f"check/submit {kind}: company", 200),
                   "url": P.url(f"check/submit {kind}: url"), "source": "student"})
        # reflections of typed values in auth forms
        for role in ("student", "employer"):
            tok = csrf_from(v.get(f"/signup/{role}").text)
            S.post(v, f"/signup/{role}", "auth forms (reflection)", [f"signup {role}: email, next"], ok=(200, 303, 400), data={
                   "csrf": tok, "email": P.text(f"signup {role}: email", 200) + "@fsu.edu", "password": PW, "password2": PW + "x",
                   "next": "/" + P.text(f"signup {role}: next")})
            tok = csrf_from(v.get(f"/login/{role}").text)
            S.post(v, f"/login/{role}", "auth forms (reflection)", [f"login {role}: email, next"], ok=(200, 303, 400, 401), data={
                   "csrf": tok, "email": P.text(f"login {role}: email", 200) + "@fsu.edu", "password": "Wrong1!pass",
                   "next": "/" + P.text(f"login {role}: next")})
            tok = csrf_from(v.get(f"/forgot/{role}").text)
            S.post(v, f"/forgot/{role}", "auth forms (reflection)", [f"forgot {role}: email"], ok=(200, 303, 400), data={
                   "csrf": tok, "email": P.text(f"forgot {role}: email", 200) + "@fsu.edu"})
        tok = csrf_from(v.get("/login").text)
        S.post(v, "/login", "auth forms (reflection)", ["login start: email, next"], ok=(200, 303, 400), data={
               "csrf": tok, "email": P.text("login start: email", 200) + "@fsu.edu", "next": "/" + P.text("login start: next")})
        tok = csrf_from(v.get("/reset?token=abc").text) if "csrf" in v.get("/reset?token=abc").text else ""
        S.post(v, "/reset", "auth forms (reflection)", ["reset: token"], ok=(200, 303, 400), data={
               "csrf": tok, "token": P.text("reset: token"), "password": PW, "password2": PW})
        S.post(v, "/verify", "auth forms (reflection)", ["verify: token"], ok=(200, 303, 400), data={"token": P.text("verify: token")})
    S.step("visitor forms", visitor)

    # ---- student profile
    def student_profile():
        t = ucsrf(s1)
        r = S.post(s1, "/profile/setup/1", "student profile", ["display_name"], data={"csrf": t, "display_name": P.text("student: display_name", 60),
                   "major": "Statistics", "degree": "Bachelor's", "grad_term": "Spring 2027"})
        S.post(s1, "/profile/setup/1", "student profile", ["display_name (quotes only)"], data={"csrf": t, "display_name": "Jordan " + P.quote("student: display_name (quotes)")[:40],
               "major": "Statistics", "degree": "Bachelor's", "grad_term": "Spring 2027"})
        S.post(s1, "/profile/setup/1", "student profile", ["pronouns", "major", "minor", "headline", "bio"], data={
               "csrf": t, "display_name": "Jordan R.", "pronouns": P.text("student: pronouns", 24), "major": P.text("student: major", 80),
               "minor": P.text("student: minor", 80), "degree": "Bachelor's", "grad_term": "Spring 2027",
               "headline": P.text("student: headline", 120), "bio": "About me. " + P.text("student: bio")})
        S.post(s1, "/profile/setup/2", "student profile", ["more_skills", "looking_roles", "pref_locations"], data={
               "csrf": t, "skills": ["Python", "SQL", "Excel"], "more_skills": "Tableau, " + P.text("student: more_skills", 300) + ", Chess " + P.quote("student: more_skills (quotes)"),
               "interests": ["Data & Analytics"], "work_types": ["remote"], "job_kinds": ["internship"],
               "looking_roles": "Data Analyst, " + P.text("student: looking_roles", 60), "pref_locations": "Tampa; " + P.text("student: pref_locations", 60)})
        S.post(s1, "/profile/setup/3", "student profile", ["linkedin (javascript:)"], data={"csrf": t, "visible": "1", "allow_messages": "1",
               "allow_connections": "1", "share_resume": "1", "linkedin": P.url("student: linkedin")})
        S.post(s1, "/profile/setup/3", "student profile", ["website (quote breakout)"], data={"csrf": t, "visible": "1", "allow_messages": "1",
               "allow_connections": "1", "share_resume": "1", "website": P.urlq("student: website")})
        S.post(s1, "/profile/setup/3", "student profile", ["resume_paste"], data={"csrf": t, "visible": "1", "allow_messages": "1",
               "allow_connections": "1", "share_resume": "1", "linkedin": "linkedin.com/in/jordanrivera",
               "resume_paste": RESUME + "\nPROJECTS\n" + P.text("student: resume_paste line") + "\n- Built " + P.text("student: resume_paste bullet") + "\n"})
        # profile items: every kind, every field
        items = {
            "experience": ["title", "org", "location", "description", "x_type"],
            "education": ["org", "title", "x_major", "x_minor", "x_coursework", "description"],
            "project": ["title", "org", "url", "x_skills", "description"],
            "certification": ["title", "org", "url"],
            "organization": ["org", "title", "description"],
            "course": ["title", "org"],
            "language": ["title", "x_proficiency"],
        }
        lim = {"title": 120, "org": 120, "location": 80, "x_major": 80, "x_minor": 80, "x_skills": 200, "x_coursework": 600, "x_type": 40,
               "x_proficiency": 40}
        for kind, fields in items.items():
            data = {"csrf": t, "kind": kind, "id": "0"}
            for f in fields:
                if f != "url":
                    data[f] = P.text(f"profile item {kind}: {f}", lim.get(f))
            S.post(s1, "/profile/items", "student profile items", [f"{kind}.{f}" for f in fields if f != "url"], data=data)
            if "url" in fields:
                for lab, u in (("javascript:", P.url(f"profile item {kind}: url")), ("quote breakout", P.urlq(f"profile item {kind}: url"))):
                    d2 = {"csrf": t, "kind": kind, "id": "0", "title": "Thing " + kind, "url": u}
                    S.post(s1, "/profile/items", "student profile items", [f"{kind}.url ({lab})"], data=d2)
        # bad date on purpose: the error page re-renders what was typed
        S.post(s1, "/profile/items", "student profile items", ["experience error re-render (start)"], ok=(200, 303, 400), data={
               "csrf": t, "kind": "experience", "id": "0", "title": P.text("profile item error: title", 120), "start": P.text("profile item error: start", 20)})
    S.step("student profile", student_profile)

    # ---- employer company profile (approved employer: only fields that don't send it back to review)
    def employer_profile():
        t = ucsrf(emp)
        S.post(emp, "/profile/setup/1", "employer profile", ["tagline", "location", "about"], data={
               "csrf": t, "company": "Acme Analytics", "website": "acme.example", "industry": "Technology", "size": "11-50",
               "location": P.text("employer: location", 120), "tagline": P.text("employer: tagline", 120),
               "about": "We build analytics dashboards for Florida city governments and hire FSU interns. " + P.text("employer: about")})
        S.post(emp, "/profile/setup/1", "employer profile", ["linkedin (javascript:)"], data={
               "csrf": t, "company": "Acme Analytics", "website": "acme.example", "industry": "Technology", "size": "11-50",
               "about": "We build analytics dashboards for Florida city governments and hire FSU interns.", "linkedin": P.url("employer: linkedin")})
        S.post(emp, "/profile/setup/1", "employer profile", ["founded (error re-render)"], ok=(200, 303, 400), data={
               "csrf": t, "company": "Acme Analytics", "website": "acme.example", "founded": P.text("employer: founded", 4),
               "about": "We build analytics dashboards for Florida city governments and hire FSU interns. " + P.text("employer: about (error re-render)")})
        S.post(emp, "/profile/setup/2", "employer profile", ["contact_name", "contact_title", "fsu_connection"], data={
               "csrf": t, "contact_name": P.text("employer: contact_name", 80), "contact_title": P.text("employer: contact_title", 80),
               "fsu_connection": "We hire FSU interns. " + P.text("employer: fsu_connection")})
    S.step("employer profile", employer_profile)

    # ---- a second employer whose organization NAME and website are payloads (approved by the admin afterwards)
    def employer_two():
        c = n.client()
        uid = make_verified(_Shim(n), "employer", "hr@beta.example")
        login(c, "employer", "hr@beta.example")
        t = ucsrf(c)
        cname = P.text("employer2: company name", 120, prefix="Beta ")
        ctx["beta_company"] = cname
        S.post(c, "/profile/setup/1", "employer profile", ["company (name)"], data={
               "csrf": t, "company": cname, "website": "beta.example", "industry": "Technology", "size": "11-50", "location": "Tampa, FL",
               "about": "Beta builds payroll tools for Florida small businesses and hires FSU students each year."})
        S.post(c, "/profile/setup/1", "employer profile", ["website (quote breakout)"], data={
               "csrf": t, "company": cname, "website": P.urlq("employer2: website"), "about": "Beta builds payroll tools for Florida small businesses."})
        S.post(c, "/profile/setup/2", "employer profile", ["contact_name (2)"], data={
               "csrf": t, "contact_name": P.text("employer2: contact_name", 80), "contact_title": "Recruiter",
               "fsu_connection": "Alumni-founded company that hires FSU interns."})
        a = admin(n)
        S.post(a, f"/admin/employers/{uid}/approve", "admin actions", ["approve employer2"], data={"csrf": admin_csrf(a, "/admin/employers"),
               "note": P.text("admin: employer approve note", 300)}, who="admin")
        ctx.update(beta=c, beta_id=uid, adm=a)
        # third employer, rejected with a note
        g, gid = employer(n, "hr@gamma.example", approve=False, company="Gamma Co")
        S.post(a, f"/admin/employers/{gid}/reject", "admin actions", ["employer reject note"], data={"csrf": admin_csrf(a, "/admin/employers"),
               "note": P.text("admin: employer reject note", 300)}, who="admin")
        ctx.update(gamma=g, gamma_id=gid)
    S.step("employer two/three", employer_two)

    # ---- job listings through the real /post form
    def jobs_post():
        c, cname = ctx.get("beta") or emp, ctx.get("beta_company") or "Acme Analytics"
        tok = csrf_from(c.get("/post").text)
        data = {"csrf": tok, "title": P.text("job/post: title", 120, prefix="Analyst "), "company": cname, "category": "Data & Analytics",
                "work_type": "remote", "location": P.text("job/post: location", 120),
                "description": "Paid summer internship for FSU students. Use SQL, Python and Tableau to build dashboards for city clients. $18/hour. "
                               + P.text("job/post: description"),
                "apply_url": "", "contact": P.text("job/post: contact", 200), "poster_name": P.text("job/post: poster_name", 80),
                "poster_title": P.text("job/post: poster_title", 80), "direct": "1", "show_email": "1",
                "rkind": ["skill", "cert"], "rlabel": [P.text("job/post: qualification 1", 40), P.text("job/post: qualification 2", 40)], "rmust": ["1", "0"],
                "easy_apply": "1", "qtext": ["Why this role? " + P.text("job/post: easy question 1", 200), P.text("job/post: easy question 2", 200)],
                "qkind": ["long", "short"], "qreq": ["1", "0"], "expiry_days": "30"}
        r = S.post(c, "/post", "job listings (/post)", ["title", "location", "description", "contact", "poster_name", "poster_title",
                   "qualifications x2", "quick-apply questions x2"], data=data, who="employer2")
        jid = (S.ids("SELECT MAX(id) FROM jobs") or [None])[0]
        if jid and jid != job_a:
            ctx["job_b"] = jid
        for label, url in (("apply_url (javascript:)", P.url("job/post: apply_url")), ("apply_url (quote breakout)", P.urlq("job/post: apply_url"))):
            tok = csrf_from(c.get("/post").text)
            d = dict(data, csrf=tok, apply_url=url, easy_apply="", qtext=[], qkind=[], qreq=[], rkind=[], rlabel=[], rmust=[],
                     title="Data Intern", location="Tampa, FL", contact="", poster_name="Pat", poster_title="Recruiter",
                     description="Paid summer internship for FSU students. Use SQL and Python to build dashboards. $18/hour.")
            S.post(c, "/post", "job listings (/post)", [label], data=d, who="employer2")
        # a contact that's a link
        tok = csrf_from(c.get("/post").text)
        S.post(c, "/post", "job listings (/post)", ["contact (javascript:)"], data=dict(data, csrf=tok, contact=P.url("job/post: contact url"),
               easy_apply="", qtext=[], qkind=[], qreq=[], rkind=[], rlabel=[], rmust=[], title="Data Intern 2", location="Tampa, FL",
               description="Paid summer internship for FSU students. Use SQL and Python to build dashboards. $18/hour."), who="employer2")
        # visitor posting (if the form allows it)
        v = n.client()
        page = v.get("/post")
        if page.status_code == 200 and 'name="csrf"' in page.text:
            S.post(v, "/post", "job listings (/post)", ["visitor post: title, company, description, poster"], ok=(200, 303, 400), data={
                   "csrf": csrf_from(page.text), "title": P.text("visitor job: title", 120), "company": P.text("visitor job: company", 120),
                   "category": "Other", "work_type": "remote", "location": P.text("visitor job: location", 120),
                   "description": "Paid internship for students, $15/hour, flexible schedule. " + P.text("visitor job: description"),
                   "apply_url": "", "contact": "", "poster_name": P.text("visitor job: poster_name", 80), "poster_title": "HR", "direct": "1"}, who="visitor")
        # approve everything pending (admin free text: reason)
        a = ctx.get("adm") or admin(n)
        ctx["adm"] = a
        pend = S.ids("SELECT id FROM jobs WHERE review_status != 'approved'")
        for j in pend:
            S.post(a, f"/admin/approve/{j}", "admin actions", [f"approve job {j}"], data={"csrf": admin_csrf(a)}, who="admin")
        # a listing the admin rejects with a reason
        jr = n.app.add_job({"title": "Reject me", "company": "Acme Analytics", "category": "Other", "work_type": "remote", "location": "",
                            "description": "Some listing that a reviewer will reject for the sweep, paid $15/hour.", "apply_url": "", "contact": ""},
                           employer_id=eid)["id"]
        S.post(a, f"/admin/reject/{jr}", "admin actions", ["job reject reason"], data={"csrf": admin_csrf(a), "reason": P.text("admin: job reject reason", 300)}, who="admin")
        ctx["job_rej"] = jr
    S.step("job listings via /post", jobs_post)

    # ---- the same fields straight through add_job (covers renderers even when a form validator refuses a payload)
    def jobs_direct():
        q = [{"q": P.text("job(add_job): question long", 200), "kind": "long", "required": True},
             {"q": "Authorized? " + P.text("job(add_job): question yesno", 200), "kind": "yesno", "required": True},
             {"q": P.text("job(add_job): question short", 200), "kind": "short", "required": False}]
        job = n.app.add_job({"title": P.text("job(add_job): title", 120), "company": "Acme Analytics", "category": "Data & Analytics",
                             "work_type": "remote", "location": P.text("job(add_job): location", 120),
                             "description": "Summer data internship, paid $18/hour. " + P.text("job(add_job): description"),
                             "apply_url": "https://acme.example/careers", "contact": P.text("job(add_job): contact", 200),
                             "poster_name": P.text("job(add_job): poster_name", 80), "poster_title": P.text("job(add_job): poster_title", 80),
                             "easy_apply": 1, "questions": q,
                             "requirements": [{"kind": "skill", "label": P.text("job(add_job): requirement", 40), "must": True}]}, employer_id=eid)
        n.app.set_review(job["id"], "approved", "legit")
        ctx["job_c"] = job["id"]
        S.seeded["job listings (add_job, direct)"] += ["title", "location", "description", "contact", "poster_name", "poster_title",
                                                       "3 questions", "requirement"]
    S.step("job listings via add_job", jobs_direct)

    # ---- listing edit form
    def listing_edit():
        jid = ctx.get("job_a")
        form = emp.get(f"/hiring/{jid}/edit").text
        tok = re.search(r'name="csrf" value="([^"]+)"', form.split('action="/hiring/')[1]).group(1)
        S.post(emp, f"/hiring/{jid}/edit", "job listings (edit)", ["title", "location", "description", "poster_name", "poster_title", "contact"], data={
               "csrf": tok, "title": P.text("job/edit: title", 120, prefix="Data "), "company": "Acme Analytics", "category": "Data & Analytics",
               "work_type": "remote", "location": P.text("job/edit: location", 120),
               "description": "Summer data internship. Use SQL, Python and Tableau to build dashboards. Paid $18/hour. " + P.text("job/edit: description"),
               "apply_url": "https://acme.example/careers", "contact": P.text("job/edit: contact", 200), "poster_name": P.text("job/edit: poster_name", 80),
               "poster_title": P.text("job/edit: poster_title", 80), "direct": "1"})
        S.post(emp, f"/hiring/{jid}/edit", "job listings (edit)", ["apply_url (javascript:)"], ok=(200, 303, 400), data={
               "csrf": tok, "title": "Data Analyst Intern", "company": "Acme Analytics", "category": "Data & Analytics", "work_type": "remote",
               "location": "Tallahassee, FL", "description": "Summer data internship. Use SQL, Python and Tableau. Paid $18/hour.",
               "apply_url": P.url("job/edit: apply_url"), "contact": "", "poster_name": "Pat Lee", "poster_title": "Recruiter", "direct": "1"})
        a = ctx.get("adm") or admin(n)
        for j in S.ids("SELECT id FROM jobs WHERE review_status != 'approved' AND id != ?", (ctx.get("job_rej") or 0,)):
            a.post(f"/admin/approve/{j}", data={"csrf": admin_csrf(a)})
    S.step("listing edit", listing_edit)

    # ---- quick apply (answers + note) and the hiring tracker (stage notes, applicant row notes)
    def quick_apply_and_hiring():
        job = ctx.get("job_c")
        t = ucsrf(s1)
        S.post(s1, f"/job/{job}/easy", "quick apply", ["a0", "a1 (error re-render)"], ok=(200, 303, 400), data={
               "csrf": t, "a0": P.text("easy apply: a0 (bad a1)"), "a1": P.text("easy apply: a1 yes/no", 40), "a2": "x", "note": "hi", "share_resume": "1"})
        S.post(s1, f"/job/{job}/easy", "quick apply", ["a0 long answer", "a2 short answer", "note"], data={
               "csrf": t, "a0": "I love data. " + P.text("easy apply: a0"), "a1": "Yes", "a2": P.text("easy apply: a2", 200),
               "note": P.text("easy apply: note"), "share_resume": "1"})
        jb = ctx.get("job_b")
        if jb:
            tb = ucsrf(s2)
            S.post(s2, f"/job/{jb}/easy", "quick apply", ["a0 (job_b)", "a1 short", "note (job_b)"], data={
                   "csrf": tb, "a0": "Because. " + P.text("easy apply job_b: a0"), "a1": P.text("easy apply job_b: a1", 200),
                   "note": P.text("easy apply job_b: note"), "share_resume": "1"})
        te = ucsrf(emp, "/hiring")
        S.post(emp, f"/hiring/{job}/save", "hiring tracker", ["save match"], data={"csrf": te, "student": ctx["sid2"]})
        S.post(emp, "/hiring/applicants/row", "hiring tracker", ["applicant row back"], ok=(200, 303, 400), data={"csrf": te, "job": job,
               "student": ctx["sid1"], "stage": "reviewing", "rating": "4", "note": "ok", "back": P.text("hiring: back param")})
        S.post(emp, "/hiring/applicants/bulk", "hiring tracker", ["bulk back"], ok=(200, 303, 400), data={"csrf": te,
               "sel": [f"{job}:{ctx['sid1']}"], "do": "stage", "stage": "reviewing", "back": P.text("hiring: bulk back")})
        S.post(emp, "/hiring/applicants/row", "hiring tracker", ["applicant row note"], data={"csrf": te, "job": job, "student": ctx["sid1"],
               "stage": "reviewing", "rating": "4", "note": P.text("hiring: applicant row note"), "back": ""})
        S.post(emp, f"/hiring/{job}/stage", "hiring tracker", ["stage note"], data={"csrf": te, "student": ctx["sid2"], "stage": "interviewing",
               "note": P.text("hiring: stage note")})
    S.step("quick apply + hiring", quick_apply_and_hiring)

    # ---- team: invite, join with name/title, edit own card
    def team():
        net_ = n
        net_.mailer.outbox.clear()
        te = ucsrf(emp, "/team")
        S.post(emp, "/team/invite", "team", ["invite email (error re-render)"], ok=(200, 303, 400), data={"csrf": te,
               "email": P.text("team: invite email", 200) + "@acme.example", "role": "recruiter"})
        S.post(emp, "/team/invite", "team", ["invite"], data={"csrf": te, "email": "dana@acme.example", "role": "recruiter"})
        mail = [m for m in net_.mailer.outbox if m["to"] == "dana@acme.example"][-1]
        tok = re.search(r"/team/join\?token=([\w-]+)", mail["body"]).group(1)
        d = n.client()
        did = make_verified(_Shim(n), "employer", "dana@acme.example")
        login(d, "employer", "dana@acme.example")
        S.post(d, "/team/join", "team", ["join name (error re-render)"], ok=(200, 303), data={"csrf": ucsrf(d, "/team/join?token=" + tok), "token": tok,
               "name": P.text("team: join name", 80), "title": P.text("team: join title (error re-render)", 80)})
        S.post(d, "/team/join", "team", ["join title"], data={"csrf": ucsrf(d, "/team/join?token=" + tok), "token": tok,
               "name": "Dana Whitfield", "title": P.text("team: join title", 80)})
        S.post(d, "/team/me", "team", ["my name (error re-render)"], data={"csrf": ucsrf(d, "/team"), "name": P.text("team: me name", 80),
               "title": "Recruiter"})
        S.post(d, "/team/me", "team", ["my title"], data={"csrf": ucsrf(d, "/team"), "name": "Dana Whitfield",
               "title": P.text("team: me title", 80)})
        S.post(d, "/team/me", "team", ["my name/title (quotes only)"], data={"csrf": ucsrf(d, "/team"), "name": "Dana " + P.quote("team: me name (quotes)"),
               "title": "Recruiter " + P.quote("team: me title (quotes)")})
        ctx.update(dana=d, dana_id=did, invite_tok=tok)
        S.post(emp, "/team/invite", "team", ["second invite (pending)"], data={"csrf": ucsrf(emp, "/team"), "email": "sam@acme.example", "role": "admin"})
    S.step("team", team)

    # ---- feed posts and comments
    def feed():
        t = ucsrf(s1)
        S.post(s1, "/feed/post", "feed", ["post body"], data={"csrf": t, "kind": "question",
               "body": "Question for FSU students: " + P.text("feed: post body"), "link": ""})
        S.post(s1, "/feed/post", "feed", ["post link (with query payload)"], data={"csrf": t, "kind": "question",
               "body": "Has anyone applied to this one before?", "link": "https://acme.example/jobs?x=" + P._tag("feed: link query") + "%22%3E%3Cx-xss"})
        S.post(s1, "/feed/post", "feed", ["post link (quote breakout)"], data={"csrf": t, "kind": "question",
               "body": "Question for FSU students about this link", "link": P.urlq("feed: post link")})
        S.post(s1, "/feed/post", "feed", ["post link (javascript:)"], data={"csrf": t, "kind": "tip",
               "body": "Tip for FSU students about this link", "link": P.url("feed: post link js")})
        S.post(s1, "/feed/post", "feed", ["post kind"], ok=(200, 303, 400), data={"csrf": t, "kind": P.text("feed: kind", 40),
               "body": "Another question for FSU students about internships", "link": ""})
        S.post(emp, "/feed/post", "feed", ["employer post body"], data={"csrf": ucsrf(emp), "kind": "info_session",
               "body": "Info session next week for FSU students. " + P.text("feed: employer post body"), "link": ""})
        a = ctx.get("adm") or admin(n)
        for pid in S.ids("SELECT id FROM posts"):
            a.post(f"/admin/posts/{pid}/publish", data={"csrf": admin_csrf(a)})
        pids = S.ids("SELECT id FROM posts ORDER BY id")
        if pids:
            S.post(s2, f"/feed/{pids[0]}/comment", "feed", ["comment body"], data={"csrf": ucsrf(s2), "body": "Yes! " + P.text("feed: comment")})
            S.post(s2, f"/feed/{pids[0]}/report", "feed", ["report post"], data={"csrf": ucsrf(s2)})
            S.post(s2, f"/feed/{pids[0]}/save", "feed", ["save next param"], ok=(200, 303, 400), data={"csrf": ucsrf(s2), "next": "/" + P.text("feed: save next")})
            for cid in S.ids("SELECT id FROM post_comments"):
                a.post(f"/admin/comments/{cid}/publish", data={"csrf": admin_csrf(a)})
                a.post(f"/admin/comments/{cid}/approve", data={"csrf": admin_csrf(a)})
    S.step("feed", feed)

    # ---- messages, templates, interview scheduling
    def messages():
        job = ctx.get("job_a")
        te = ucsrf(emp)
        r = S.post(emp, "/messages/new", "messages", ["first message (employer)"], data={"csrf": te, "to": ctx["sid1"], "job": job,
                   "body": "Hello, we'd like to talk about our internship. " + P.text("messages: employer first message")})
        cid = _loc_id(r, r"/messages/(\d+)")
        if not cid:
            raise RuntimeError("no conversation: " + _reason(r))
        ctx["cid"] = cid
        t1 = ucsrf(s1)
        S.post(s1, f"/messages/{cid}/send", "messages", ["reply (student)"], data={"csrf": t1, "body": "Thanks! " + P.text("messages: student reply")})
        S.post(s1, f"/api/messages/{cid}", "messages", ["api send (student)"], json={"body": "Also " + P.text("messages: api send")},
               headers={"X-CSRF-Token": t1})
        S.post(emp, f"/messages/{cid}/send", "messages", ["reply (employer)"], data={"csrf": ucsrf(emp), "body": "Great. " + P.text("messages: employer reply")})
        jb = ctx.get("job_b")
        if jb and ctx.get("beta"):
            r2 = S.post(s2, "/messages/new", "messages", ["first message (student to employer)"], data={"csrf": ucsrf(s2), "to": ctx["beta_id"],
                        "job": jb, "body": "Hi, is the role still open? " + P.text("messages: student first message")})
            ctx["cid2"] = _loc_id(r2, r"/messages/(\d+)")
        # templates
        S.post(emp, "/messages/templates", "message templates", ["title", "body"], data={"csrf": ucsrf(emp), "title": P.text("template: title", 80),
               "body": "Hi {first_name}, " + P.text("template: body")})
        tids = S.ids("SELECT id FROM message_templates ORDER BY id DESC")
        if tids:
            S.post(emp, f"/messages/templates/{tids[0]}", "message templates", ["edit title", "edit body"], data={"csrf": ucsrf(emp),
                   "title": P.text("template edit: title", 80), "body": "Thanks {first_name}! " + P.text("template edit: body")})
            S.post(emp, "/messages/templates", "message templates", ["title (error re-render)"], ok=(200, 303, 400), data={"csrf": ucsrf(emp),
                   "title": P.text("template: long title") + "x" * 90, "body": P.text("template: body (error re-render)")})
        # interview scheduling
        sc = ucsrf(emp, f"/messages/{cid}")
        r = S.post(emp, f"/messages/{cid}/interview", "interview scheduling", ["location", "note"], data={"csrf": sc, "format": "in_person",
                   "location": P.text("interview: location", 200), "note": P.text("interview: note"),
                   "d1": _day(3), "t1": "14:00", "m1": "30", "d2": _day(4), "t2": "10:30", "m2": "45"})
        S.post(emp, f"/messages/{cid}/interview", "interview scheduling", ["video link (javascript:)"], ok=(200, 303, 400), data={"csrf": sc,
               "format": "video", "location": P.url("interview: video link"), "note": "x", "d1": _day(5), "t1": "14:00", "m1": "30"})
        S.post(emp, f"/messages/{cid}/interview", "interview scheduling", ["error re-render (bad slot)"], ok=(200, 303, 400), data={"csrf": sc,
               "format": "phone", "location": P.text("interview err: location", 200), "note": P.text("interview err: note"),
               "d1": P.text("interview err: d1", 20), "t1": P.text("interview err: t1", 10), "m1": "30"})
        S.post(emp, f"/messages/{cid}/interview", "interview scheduling", ["error re-render (non-numeric re)"], ok=(200, 303, 400), data={"csrf": sc,
               "format": "phone", "location": "x", "note": "x", "d1": "", "t1": "", "re": P.text("interview err: re", 20)})
        pids = S.ids("SELECT id FROM interview_proposals WHERE conversation_id = ? ORDER BY id DESC", (cid,))
        if pids:
            S.post(s1, f"/messages/{cid}/interview/{pids[0]}/decline", "interview scheduling", ["decline note"], data={"csrf": ucsrf(s1, f"/messages/{cid}"),
                   "note": P.text("interview: decline note")})
            S.post(emp, f"/messages/{cid}/interview", "interview scheduling", ["location 2", "note 2"], data={"csrf": ucsrf(emp, f"/messages/{cid}"),
                   "format": "in_person", "location": P.text("interview2: location", 200), "note": P.text("interview2: note"),
                   "d1": _day(6), "t1": "11:00", "m1": "30"})
            p2 = S.ids("SELECT id FROM interview_proposals WHERE conversation_id = ? ORDER BY id DESC", (cid,))
            slots = S.ids("SELECT starts_at FROM interview_slots WHERE proposal_id = ?", (p2[0],)) if p2 else []
            if slots:
                page = s1.get(f"/messages/{cid}").text
                m = re.search(r'name="slot" value="([^"]+)"', page)
                if m:
                    S.post(s1, f"/messages/{cid}/interview/{p2[0]}/pick", "interview scheduling", ["pick slot"], data={"csrf": ucsrf(s1, f"/messages/{cid}"), "slot": m.group(1)})
        S.post(s2, f"/messages/{ctx['cid2']}/report", "messages", ["report convo"], data={"csrf": ucsrf(s2)}) if ctx.get("cid2") else None
    S.step("messages + scheduling", messages)

    # ---- connections / follows
    def network():
        S.post(s2, "/network/connect", "network", ["connection note"], data={"csrf": ucsrf(s2), "to": ctx["sid1"], "note": P.text("network: connect note", 300)})
        S.post(s1, "/network/follow", "network", ["follow next"], ok=(200, 303, 400), data={"csrf": ucsrf(s1), "employer": ctx["eid"],
               "next": "/" + P.text("network: follow next")})
    S.step("network", network)

    # ---- resume studio
    def resume():
        t = ucsrf(s1)
        S.post(s1, "/resume/upload", "resume studio", ["paste"], data={"csrf": t, "paste": RESUME + "\n- Led " + P.text("resume: paste bullet") + "\n"})
        S.post(s1, "/resume/upload", "resume studio", ["upload file"], data={"csrf": t},
               files={"resume": (P.text("resume: upload filename", 100) + ".txt", (RESUME + "\n- " + P.text("resume: upload text")).encode(), "text/plain")})
        S.post(s1, "/resume/save", "resume studio", ["save text"], data={"csrf": t, "text": RESUME + "\n- Ran " + P.text("resume: save text") + "\n"})
        S.post(s1, "/resume/apply", "resume studio", ["apply old/new"], ok=(200, 303, 400), data={"csrf": t,
               "old": "Responsible for cleaning survey data in Excel", "new": "Cleaned " + P.text("resume: apply new")})
        S.post(s1, "/resume/accept", "resume studio", ["accept summary"], ok=(200, 303, 400), data={"csrf": t, "ctx": "main", "kind": "summary",
               "old": "", "new": "Statistics student. " + P.text("resume: accept summary")})
        S.post(s1, "/resume/accept", "resume studio", ["accept skills"], ok=(200, 303, 400), data={"csrf": t, "ctx": "main", "kind": "skills",
               "old": "", "new": "Figma, " + P.text("resume: accept skills", 60)})
        S.post(s1, "/resume/bullet", "resume studio", ["bullet (form)"], data={"csrf": t, "bullet": "Led " + P.text("resume: bullet form", 300)})
        S.post(s1, "/api/resume/bullet", "resume studio", ["bullet (api)"], json={"bullet": "Helped " + P.text("resume: bullet api", 300)},
               headers={"X-CSRF-Token": t})
        S.post(s1, "/resume/tailor", "resume studio", ["tailor title", "tailor description"], data={"csrf": t, "job_id": "",
               "title": P.text("resume: tailor title", 120), "description": "Use SQL and Tableau to build dashboards every week. " + P.text("resume: tailor description"),
               "mode": "builtin"})
        S.post(s1, "/resume/tailor", "resume studio", ["tailor job_id (error)"], ok=(200, 303, 400), data={"csrf": t, "job_id": P.text("resume: tailor job_id", 30),
               "title": "", "description": "", "mode": P.text("resume: tailor mode", 30)})
        S.post(s1, "/resume/versions", "resume studio", ["version name", "version body"], data={"csrf": t, "name": P.text("resume: version name", 80),
               "body": RESUME + "\n- " + P.text("resume: version body") + "\n"})
        S.post(s1, "/resume/versions", "resume studio", ["version for job"], data={"csrf": t, "name": "For job " + P.text("resume: version name 2", 60),
               "body": RESUME, "job_id": str(ctx.get("job_c") or "")})
        for jid in (ctx.get("job_c"), ctx.get("job_b")):
            if jid:
                S.post(s1, f"/job/{jid}/tailor/save", "resume studio", [f"tailor save job {jid} (undo)"], ok=(200, 303, 400), data={"csrf": t,
                       "undo": P.text("resume: tailor undo", 200)})
        S.post(s1, "/resume/optimized/save", "resume studio", ["optimized save (src/undo)"], ok=(200, 303, 400), data={"csrf": t,
               "src": P.text("resume: optimized src", 40), "undo": P.text("resume: optimized undo", 200)})
    S.step("resume studio", resume)

    # ---- career assistant
    def assistant():
        t = ucsrf(s1)
        S.post(s1, "/assistant", "career assistant", ["question (form)"], data={"csrf": t, "q": "Find analyst internships " + P.text("assistant: q form"), "cid": ""})
        S.post(s1, "/assistant/memory/add", "career assistant", ["memory fact"], data={"csrf": t, "fact": "Wants remote work " + P.text("assistant: memory fact", 200)})
        S.post(s1, "/assistant/memory/add", "career assistant", ["memory fact (quotes only)"], data={"csrf": t,
               "fact": "I prefer remote internships " + P.quote("assistant: memory fact (quotes)")})
        S.post(s1, "/api/assistant/send", "career assistant", ["question (api send)"], json={"q": "Remote data jobs " + P.text("assistant: q api send")},
               headers={"X-CSRF-Token": t})
        S.post(s1, "/api/assistant", "career assistant", ["history user/assistant (api)"], json={"history": [
               {"role": "user", "text": "analyst " + P.text("assistant: history user")},
               {"role": "assistant", "text": "Sure " + P.text("assistant: history assistant")},
               {"role": "user", "text": "more " + P.text("assistant: history user 2")}]}, headers={"X-CSRF-Token": t})
        chats = S.ids("SELECT id FROM assistant_chats ORDER BY id")
        if chats:
            S.post(s1, f"/assistant/c/{chats[0]}/pin", "career assistant", ["pin v"], ok=(200, 303, 400), data={"csrf": t,
                   "job": str(ctx.get("job_c") or 0), "v": P.text("assistant: pin v", 20)})
            S.post(s1, f"/assistant/c/{chats[0]}/feedback", "career assistant", ["feedback v"], ok=(200, 303, 400), data={"csrf": t,
                   "m": "1", "v": P.text("assistant: feedback v", 20)})
    S.step("career assistant", assistant)

    # ---- events
    def events():
        import events as ev
        day = ev.local(time.time() + 3 * 86400).strftime("%Y-%m-%d")
        base = {"kind": "info_session", "date": day, "time": "18:00", "duration": "60", "capacity": "", "job_id": ""}
        r = S.post(emp, "/events/new", "events", ["title", "description", "location", "majors"], data={**base, "csrf": ucsrf(emp, "/events/new"),
                   "title": P.text("event: title", 120, prefix="Info "), "description": "Meet our team and hear about internships. " + P.text("event: description"),
                   "format": "in_person", "location": P.text("event: location", 120), "meeting_url": "", "majors": "Statistics"})
        e1 = _loc_id(r, r"/events/(\d+)")
        S.post(emp, "/events/new", "events", ["majors (error re-render)"], ok=(200, 303, 400), data={**base, "csrf": ucsrf(emp, "/events/new"),
               "title": "Info session about majors", "description": "Meet our team and hear about internships for these majors.",
               "format": "in_person", "location": "Room 2", "meeting_url": "", "majors": "Statistics, " + P.text("event: majors", 60)})
        S.post(emp, "/events/new", "events", ["meeting_url (javascript:)"], ok=(200, 303, 400), data={**base, "csrf": ucsrf(emp, "/events/new"),
               "title": "Virtual info session", "description": "Meet our team and hear about our summer internships.", "format": "virtual",
               "location": "", "meeting_url": P.url("event: meeting_url"), "majors": ""})
        r = S.post(emp, "/events/new", "events", ["meeting_url (zoom + quote breakout)"], ok=(200, 303, 400), data={**base, "csrf": ucsrf(emp, "/events/new"),
                   "title": "Virtual info session 2", "description": "Meet our team and hear about our summer internships.", "format": "virtual",
                   "location": "", "meeting_url": 'https://acme.zoom.us/j/1?pwd="><x-xss-' + P._tag("event: meeting_url zoom") + '>', "majors": ""})
        S.post(emp, "/events/new", "events", ["error re-render (bad date)"], ok=(200, 303, 400), data={**base, "csrf": ucsrf(emp, "/events/new"),
               "title": P.text("event err: title", 120), "description": P.text("event err: description"), "format": "in_person",
               "location": P.text("event err: location", 120), "meeting_url": "", "majors": "", "date": P.text("event err: date", 20),
               "time": P.text("event err: time", 10), "capacity": P.text("event err: capacity", 10)})
        if e1:
            S.post(emp, f"/events/{e1}/edit", "events", ["edit title", "edit description", "edit location"], data={**base, "csrf": ucsrf(emp, f"/events/{e1}/edit"),
                   "title": P.text("event edit: title", 120, prefix="Info "), "description": "Updated: meet our team. " + P.text("event edit: description"),
                   "format": "in_person", "location": P.text("event edit: location", 120), "meeting_url": "", "majors": "Statistics"})
        a = ctx.get("adm") or admin(n)
        for e in S.ids("SELECT id FROM events"):
            S.post(a, f"/admin/events/{e}/approve", "admin actions", [f"approve event {e} note"], data={"csrf": admin_csrf(a, "/admin/events"),
                   "note": P.text("admin: event approve note", 300)}, who="admin")
        # one more to reject with a note
        r = emp.post("/events/new", data={**base, "csrf": ucsrf(emp, "/events/new"), "title": "Reject this event", "format": "in_person",
                                          "description": "An event the reviewer will reject during the sweep.", "location": "Room 1", "meeting_url": "", "majors": ""})
        e3 = _loc_id(r, r"/events/(\d+)")
        if e3:
            S.post(a, f"/admin/events/{e3}/reject", "admin actions", ["event reject note"], data={"csrf": admin_csrf(a, "/admin/events"),
                   "note": P.text("admin: event reject note", 300)}, who="admin")
        if e1:
            S.post(s1, f"/events/{e1}/rsvp", "events", ["rsvp next"], ok=(200, 303, 400), data={"csrf": ucsrf(s1), "status": "going",
                   "next": "/" + P.text("event: rsvp next")})
        ctx["event"] = e1
    S.step("events", events)

    # ---- inbound email (forwarded scam emails) -> cases / emails
    def inbound():
        monkeypatch.setenv("INBOUND_EMAIL_TOKEN", "tok123")
        v = n.client()
        S.post(v, "/inbound/email?token=tok123", "inbound email", ["from", "subject", "text"], ok=(200, 202, 204, 303), data={
               "from": "Jordan <jordan@fsu.edu>", "subject": "Fwd: offer " + P.text("inbound: subject", 150),
               "text": "---------- Forwarded message ---------\nFrom: HR " + P.text("inbound: orig sender", 80) +
                       " <hr@quickcash.example>\nSubject: Job offer\n\nCongratulations, send a $50 deposit by gift card. " + P.text("inbound: body")})
    S.step("inbound email", inbound)

    # ---- admin free-text tools
    a = ctx.get("adm") or admin(n)
    ctx["adm"] = a

    def whoami():
        S.post(a, "/admin/whoami", "admin actions", ["reviewer name"], data={"csrf": admin_csrf(a, "/admin/checks"), "name": P.text("admin: reviewer name", 40),
               "back": "/admin/checks"}, who="admin")
    S.step("admin whoami", whoami)

    def check_label():
        page = a.get("/admin/checks").text
        g = re.search(r'name="group" value="([^"]+)"', page)
        if not g:
            raise RuntimeError("no submitted check groups on /admin/checks")
        S.post(a, "/admin/checks/label", "admin actions", ["check label reason"], data={"csrf": csrf_from(page), "group": g.group(1), "label": "scam",
               "reason": P.text("admin: check label reason", 300)}, who="admin")
    S.step("admin check label", check_label)

    def intel():
        page = a.get("/admin/intel").text
        S.post(a, "/admin/intel/window", "admin actions", ["risk window name", "risk window note"], data={"csrf": csrf_from(page),
               "name": P.text("admin: window name", 80), "start_md": "10-01", "end_md": "10-07", "note": P.text("admin: window note", 200)}, who="admin")
        h = re.search(r'name="h" value="([^"]+)"', page)
        if h:
            S.post(a, "/admin/intel/indicator/revoke", "admin actions", ["indicator revoke reason"], data={"csrf": csrf_from(page), "h": h.group(1),
                   "reason": P.text("admin: revoke reason", 200)}, who="admin")
        else:
            S.skipped.append(("admin indicator revoke reason", "no indicators listed on /admin/intel"))
    S.step("admin intel", intel)

    def decoys():
        monkeypatch.setenv("DECOY_ENABLED", "1")
        r = a.get("/admin/decoys")
        if 'name="csrf"' not in r.text:
            raise RuntimeError(f"/admin/decoys has no form (status {r.status_code})")
        page = r.text
        S.post(a, "/admin/decoys/log", "admin actions", ["decoy log body (in)"], ok=(200, 303, 400), data={"csrf": csrf_from(page), "persona": "maya",
               "body": "Hi, send me your bank login to get the job. " + P.text("admin: decoy body"), "direction": "in"}, who="admin")
        S.post(a, "/admin/decoys/log", "admin actions", ["decoy persona"], ok=(200, 303, 400), data={"csrf": csrf_from(page), "persona": P.text("admin: decoy persona", 40),
               "body": "hello there", "direction": "out"}, who="admin")
    S.step("admin decoys", decoys)

    def open_case():
        variants = [
            "Hello student, earn by rating hotel reviews online. Unlock the golden tier bonus after your first set. ",
            "Flexible gig: rate hotel reviews online from your phone each evening, unlock the golden tier bonus and withdraw weekly. ",
            "Our travel partner pays students to rate hotel reviews online. Reach the golden tier bonus in three days. ",
            "Side income for Seminoles! You rate hotel reviews online, level up to the golden tier bonus, commission paid in USDT. "]
        v = n.client()
        for i, text in enumerate(variants):
            tok = csrf_from(v.get("/check?kind=message").text)
            S.post(v, "/check/submit", "admin cases", [f"case report {i + 1} text"], data={"csrf": tok, "text": text + P.text(f"case report {i + 1}: text"),
                   "sender": P.text(f"case report {i + 1}: sender", 200), "band": "clear", "label": "scam", "kind": "message"})
        with S.db() as d:
            d.execute("UPDATE submitted_checks SET review_label = 'scam', reviewed_at = ?, band = 'clear' WHERE review_label IS NULL OR review_label = ''",
                      (time.time(),))
            d.commit()
        a.get("/admin/cases")
    S.step("admin cases (open)", open_case)

    def case_note():
        cases = S.ids("SELECT id FROM cases ORDER BY id")
        if not cases:
            raise RuntimeError("no cases were opened by the seeded checks / inbound email")
        page = a.get(f"/admin/cases/{cases[0]}").text
        S.post(a, f"/admin/cases/{cases[0]}/decide", "admin actions", ["case decide note"], data={"csrf": csrf_from(page), "status": "dismissed",
               "note": P.text("admin: case note", 300)}, who="admin")
    S.step("admin case note", case_note)

    # ---- AI output: a stand-in model that answers with payloads (prompt-injection / model output must be escaped too)
    def ai_output():
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        n.ai._transport = httpx.MockTransport(_ai_handler(P))
        t = ucsrf(s1)
        S.post(s1, "/api/assistant", "AI output", ["assistant reply (api)"], json={"history": [{"role": "user", "text": "data internships?"}]},
               headers={"X-CSRF-Token": t})
        S.post(s1, "/api/assistant/send", "AI output", ["assistant reply (send)"], json={"q": "remote analyst roles?"}, headers={"X-CSRF-Token": t})
        S.post(s1, "/resume/ai-review", "AI output", ["resume AI review"], ok=(200, 303, 400, 429, 503), data={"csrf": t})
        S.post(s1, "/api/resume/bullet", "AI output", ["bullet rewrite"], json={"bullet": "Helped with charts in Tableau"}, headers={"X-CSRF-Token": t})
        for jid in (ctx.get("job_a"), ctx.get("job_c")):
            if jid:
                S.post(s1, f"/job/{jid}/tailor/ai", "AI output", [f"tailor AI job {jid}"], ok=(200, 303, 400, 429, 503), data={"csrf": t, "undo": ""})
        S.post(s1, "/resume/optimized/ai", "AI output", ["optimized AI"], ok=(200, 303, 400, 429, 503), data={"csrf": t, "src": "main", "undo": ""})
        tok = csrf_from(s1.get("/check").text)
        S.post(s1, "/check", "AI output", ["scam check AI explanation"], data={"csrf": tok, "text": "Hello, you got the job, buy gift cards now.",
               "sender": "hr@x.example", "ai_": "1"})
    S.step("AI output", ai_output)

    # ---- the student scam check while signed in (saved checks show in history)
    def signed_in_check():
        tok = csrf_from(s1.get("/check").text)
        S.post(s1, "/check", "public check", ["text, sender (student)"], data={"csrf": tok, "text": "Hi, we saw your resume " + P.text("check: text (student)"),
               "sender": P.text("check: sender (student)", 200)})
    S.step("signed-in check", signed_in_check)
    return ctx


# ---------------------------------------------------------------- crawl

def _routes(app):
    out = []

    def walk(rs):
        for r in rs:
            if hasattr(r, "path"):
                if "GET" in (getattr(r, "methods", None) or ()):
                    out.append(r)
            elif hasattr(r, "original_router"):
                walk(r.original_router.routes)
            elif hasattr(r, "routes"):
                walk(r.routes)
    walk(app.routes)
    return out


def _qparams(route):
    d = route.dependant
    qs = list(d.query_params)
    stack = list(d.dependencies)
    while stack:
        sub = stack.pop()
        qs += list(sub.query_params)
        stack += list(sub.dependencies)
    res = []
    for q in qs:
        ann = getattr(getattr(q, "field_info", None), "annotation", None) or getattr(q, "type_", str)
        res.append((q.alias or q.name, ann))
    return res


SKIP_PREFIX = ("/static/", "/healthz", "/robots.txt")
EXTRA_QUERY = ("q", "next", "search", "loc", "from", "msg", "note", "done", "tab", "invite", "back", "kind", "src", "m")


def crawl(S: Sweep, ctx):
    n, P = S.n, S.P
    ids = {
        "job": S.ids("SELECT id FROM jobs ORDER BY id"),
        "user": S.ids("SELECT id FROM users ORDER BY id"),
        "convo": S.ids("SELECT id FROM conversations ORDER BY id"),
        "chat": S.ids("SELECT id FROM assistant_chats ORDER BY id"),
        "case": S.ids("SELECT id FROM cases ORDER BY id"),
        "post": S.ids("SELECT id FROM posts ORDER BY id"),
        "event": S.ids("SELECT id FROM events ORDER BY id"),
        "item": S.ids("SELECT id FROM profile_items ORDER BY id"),
        "version": S.ids("SELECT id FROM resume_versions ORDER BY id"),
        "email": S.ids("SELECT id FROM emails ORDER BY id"),
    }
    pairs = []
    try:
        with S.db() as d:
            pairs = d.execute("SELECT conversation_id, id FROM interview_proposals ORDER BY id").fetchall()
    except sqlite3.Error:
        pass

    def values(path, name):
        if name in ("job_id", "jid"):
            return ids["job"]
        if name == "uid":
            return ids["user"]
        if name == "cid":
            if path.startswith("/assistant"):
                return ids["chat"]
            if path.startswith("/admin/cases"):
                return ids["case"]
            return ids["convo"]
        if name == "pid":
            return ids["post"]
        if name == "eid":
            return ids["event"]
        if name == "iid":
            return ids["item"]
        if name == "vid":
            return ids["version"]
        if name == "step":
            return [1, 2, 3]
        if name == "role":
            return ["student", "employer"]
        if name == "ext":
            return ["txt", "docx", "pdf"]
        return []

    urls = []
    for r in _routes(n.app.app):
        path = r.path
        if path.startswith(SKIP_PREFIX):
            continue
        names = re.findall(r"{(\w+)(?::\w+)?}", path)
        if "/interview/{pid}" in path:
            combos = [{"cid": c, "pid": p} for c, p in pairs]
        else:
            lists = [values(path, nm) for nm in names]
            combos = [dict(zip(names, vs)) for vs in itertools.product(*lists)] if names else [{}]
        for combo in combos:
            url = path
            for k, v in combo.items():
                url = re.sub(r"{%s(?::\w+)?}" % k, str(v), url)
            urls.append((r, url))

    # Extra state-dependent pages that a plain route list can't reach.
    extra = ["/profile?welcome=1&imported=2", "/resume?tab=tailor", "/resume?tab=versions", "/resume?tab=bullets", "/hiring/applicants?show=archived",
             "/feed?tab=saved", "/feed?tab=mine", "/network?tab=requests", "/network?tab=following", "/applications?sent=1", "/events?when=all",
             "/check?m=listing", "/check?m=thread", "/check?m=school", "/admin/decoys?persona=maya&draft=1",
             "/resume?ai=1", "/resume?tab=review&ai=1", "/resume/optimized?ai=1", "/resume/optimize?ai=1"]
    for j in ids["job"]:
        extra += [f"/job/{j}/tailor?ai=1", f"/hiring/{j}?tab=candidates", f"/hiring/{j}?tab=matches", f"/hiring/{j}?tab=pipeline", f"/resume?tab=tailor&job={j}",
                  f"/job/{j}/report?scan=1", f"/messages/new?to={ctx.get('sid1')}&job={j}", f"/messages/new?to={ctx.get('eid')}&job={j}"]
    if ctx.get("invite_tok"):
        extra.append(f"/team/join?token={ctx['invite_tok']}")
    tids = S.ids("SELECT id FROM message_templates ORDER BY id")
    for t in tids:
        extra += [f"/messages/new?to={ctx.get('sid1')}&tpl={t}", f"/messages/{ctx.get('cid')}?tpl={t}"]

    a = ctx.get("adm") or admin(n)
    roles = [("visitor", n.client()), ("student", ctx["s1"]), ("student2", ctx["s2"]), ("employer", ctx["emp"]), ("admin", a)]
    if ctx.get("dana"):
        roles.append(("team member", ctx["dana"]))
    if ctx.get("beta"):
        roles.append(("employer2", ctx["beta"]))
    S.reset_limits(force=True)
    for who, c in roles:
        for _, url in urls:
            S.get(c, url, who)
        for url in extra:
            S.get(c, url, who)

    # Query-string pass: every declared string query parameter (and a few common extra names) gets a payload.
    qroutes = []
    for r in _routes(n.app.app):
        if r.path.startswith(SKIP_PREFIX):
            continue
        qroutes.append(r)
    sample_url = {}
    for r, url in urls:
        sample_url.setdefault(r.path, url)
    for r in qroutes:
        base = sample_url.get(r.path)
        if not base:
            continue
        declared = _qparams(r)
        params = {}
        for name, ann in declared:
            if ann in (int, float, bool):
                continue
            params[name] = P.text(f"query {r.path}?{name}")
        for name in EXTRA_QUERY:
            if name not in params and name not in dict(declared):
                params[name] = P.text(f"query {r.path}?{name} (undeclared)")
        qs = str(httpx.QueryParams(params))
        S.seeded["query strings"].append(f"{r.path} ({len(params)} params)")
        for who, c in roles:
            S.get(c, f"{base}?{qs}", who)

    # Emails kept in the site copy (/emails is crawled above). The outbox itself is plain text; scan it in case a body is HTML.
    for m in n.mailer.outbox:
        body = m.get("body") or ""
        if "<html" in body.lower() or "<p" in body.lower() or "<a " in body.lower():
            for tag, kind, snip in scan_html(body):
                S.hits.setdefault((tag, kind, f"email to {m.get('to')}: {m.get('subject')}"), snip)


def major_probe(S: Sweep, ctx):
    """Run last: a 'Major' qualification whose label isn't a known major. Seeded after the crawl because it can take
    down the student board; any 500s land in S.errors and any leaked marker in S.hits."""
    n, P = S.n, S.P
    c, cname = ctx.get("beta") or ctx["emp"], ctx.get("beta_company") or "Acme Analytics"
    tok = csrf_from(c.get("/post").text)
    S.post(c, "/post", "job listings (/post)", ["qualification kind=major (label)"], data={"csrf": tok, "title": "Payroll Intern", "company": cname,
           "category": "Other", "work_type": "remote", "location": "Tampa, FL", "direct": "1",
           "description": "Paid internship for FSU students. Help with payroll reports in Excel. $16/hour, flexible schedule.",
           "apply_url": "", "contact": "", "poster_name": "Pat", "poster_title": "Recruiter",
           "rkind": ["major"], "rlabel": [P.text("job/post: qualification kind=major", 40)], "rmust": ["1"]}, who="employer2")
    a = ctx["adm"]
    for j in S.ids("SELECT id FROM jobs WHERE review_status != 'approved' AND id != ?", (ctx.get("job_rej") or 0,)):
        a.post(f"/admin/approve/{j}", data={"csrf": admin_csrf(a)})
    jid = (S.ids("SELECT MAX(id) FROM jobs") or [0])[0]
    for who, cl in (("student", ctx["s1"]), ("student2", ctx["s2"]), ("visitor", n.client())):
        for url in ("/", "/jobs", f"/job/{jid}", f"/job/{jid}/tailor", "/resume?tab=tailor"):
            S.get(cl, url, who)


# ---------------------------------------------------------------- the test

def test_xss_sweep(net, monkeypatch):
    started = time.time()
    S = Sweep(net)
    ctx = seed_all(S, monkeypatch)
    seeded_at = time.time()
    crawl(S, ctx)
    S.step("major-qualification probe", lambda: major_probe(S, ctx))

    print("\n================ XSS sweep ================")
    total = sum(len(v) for v in S.seeded.values())
    print(f"Seeded {total} field(s) / steps in {seeded_at - started:.1f}s; {len(S.P.label)} unique payload markers issued")
    for feat, fields in sorted(S.seeded.items()):
        print(f"  {feat:34s} {len(fields):3d}  " + ", ".join(fields)[:300])
    print(f"Pages scanned (HTML responses): {S.pages}; JSON responses scanned for HTML fragments: {S.scanned_json}; "
          f"total time {time.time() - started:.1f}s")
    stored = {t: lab for t, lab in S.P.label.items() if not lab.startswith("query ")}
    unseen = sorted(lab for t, lab in stored.items() if t not in S.seen)
    print(f"Stored-payload markers seen in at least one response (escaped or not): {len(stored) - len(unseen)}/{len(stored)}")
    if unseen:
        print("  never seen in any response (validator refused it, field isn't displayed, or the page wasn't reached): " + "; ".join(unseen))
    if S.rejected:
        print(f"Rejected by validation ({len(S.rejected)}) - fine, the input never got in (error pages were still scanned):")
        for feat, fields, code, why in S.rejected:
            print(f"  [{code}] {feat}: {fields} -> {why}")
    if S.errors:
        print(f"Server errors (500) seen while seeding/crawling ({len(S.errors)}) - not XSS, but worth a look:")
        for where, what in sorted(S.errors.items()):
            print(f"  {where} -> {what}")
    if S.skipped:
        print(f"Skipped ({len(S.skipped)}):")
        for name, why in S.skipped:
            print(f"  {name}: {why}")

    # One line per (marker, kind); list every page it showed up on.
    grouped = defaultdict(list)
    for (tag, kind, where), snip in S.hits.items():
        grouped[(tag, kind)].append((where, snip))
    lines = []
    for (tag, kind), places in sorted(grouped.items(), key=lambda x: (S.P.label.get(x[0][0], "?"), x[0][1])):
        lines.append(f"\n  marker {tag} [{S.P.label.get(tag, 'unknown marker')}] -> {kind}  ({len(places)} page(s))")
        for where, snip in places[:6]:
            lines.append(f"\n      {where}\n        ...{snip[:120]}...")
        if len(places) > 6:
            lines.append(f"\n      ... and {len(places) - 6} more")
    if lines:
        print("XSS FINDINGS:" + "".join(lines))
    assert not grouped, f"{len(grouped)} unescaped payload(s) reached HTML in executable form:" + "".join(lines)
    # Crashes found by the sweep (e.g. an employer-typed major breaking the job board) must stay fixed too.
    assert not S.errors, f"{len(S.errors)} page(s) returned a server error: " + "; ".join(f"{w} -> {e}" for w, e in sorted(S.errors.items()))
