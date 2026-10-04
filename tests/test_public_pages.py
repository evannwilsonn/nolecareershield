"""The public pages in the elite look: the "Enter the vault" sign-in pages and the logged-out landing.
Run: python -m pytest -q tests/test_public_pages.py"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import PW, client, csrf_from, make_verified, user_login  # noqa: E402,F401

AUTH_PAGES = ("/login", "/login/student", "/login/employer", "/signup/student", "/signup/employer", "/forgot/student", "/forgot/employer")


def _scripts(html):
    return re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S)


def test_every_account_page_is_the_vault(client):
    import ui
    for path in AUTH_PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        page = r.text
        assert '<section class="vx"' in page and 'class="vx-card"' in page and 'class="vx-seal"' in page, path
        assert "The inner circle<br>for <em>FSU</em> careers." in page and 'class="vx-pillars"' in page, path
        employer = path.endswith("/employer")
        eyebrow = "// Employer access · verified organizations" if employer else "// Florida State University · private access"
        assert eyebrow in page, path
        assert 'class="crest"' in page and "@fsu.edu</b>" in page
        # Strict page policy: only same-origin scripts and the one hashed inline script (password Show / checklist).
        for attrs, body in _scripts(page):
            assert ('src="/static/' in attrs and not body.strip()) or body == ui.PAGE_SCRIPT, (path, attrs)
        assert "—" not in re.sub(r"<title>.*?</title>", "", page)
    assert "Enter the vault" in client.get("/login/student").text and "Sign in securely" in client.get("/login/employer").text


def test_forms_keep_their_fields_and_csrf(client):
    st = client.get("/login/student").text
    for bit in ('action="/login/student"', 'name="email"', 'name="password"', 'name="csrf"', 'name="next"', 'href="/forgot/student"',
                'href="/signup/student"', 'data-showpw="f-password"', 'autocomplete="username"', 'autocomplete="current-password"'):
        assert bit in st, bit
    su = client.get("/signup/employer").text
    for bit in ('action="/signup/employer"', 'name="password2"', 'name="website"', 'data-pwcheck', 'class="rules"', 'autocomplete="new-password"'):
        assert bit in su, bit
    start = client.get("/login").text
    assert 'action="/login"' in start and 'id="s-email"' in start and "Continue with email" in start and 'href="/employers"' in start


def test_fsu_check_only_for_an_address_the_server_checked(client):
    blank = client.get("/login/student").text
    assert "Use your @fsu.edu address" in blank and "FSU.EDU VERIFIED" not in blank
    # Step one validated the address: the password page shows the green check.
    r = client.post("/login", data={"csrf": csrf_from(client.get("/login").text), "email": "Jane@FSU.edu"})
    assert "FSU.EDU VERIFIED" in r.text and 'value="jane@fsu.edu"' in r.text and 'aria-describedby="f-email-hint"' in r.text
    # A wrong password re-renders with the check (the address is valid; it says nothing about whether an account exists).
    make_verified(client, "student", "jane@fsu.edu")
    client.cookies.clear()
    tok = csrf_from(client.get("/login/student").text)
    bad = client.post("/login/student", data={"csrf": tok, "email": "jane@fsu.edu", "password": "Wrong!pass1", "next": ""})
    none = client.post("/login/student", data={"csrf": tok, "email": "ghost@fsu.edu", "password": "Wrong!pass1", "next": ""})
    assert bad.status_code == none.status_code == 401
    assert "FSU.EDU VERIFIED" in bad.text and "FSU.EDU VERIFIED" in none.text
    assert "The email or password is incorrect." in bad.text
    # Look-alikes and other domains never get it, and neither does the employer side.
    for email in ("jane@fsu.edu.evil.com", "jane@notfsu.edu", "not an email"):
        r = client.post("/login/student", data={"csrf": tok, "email": email, "password": "x", "next": ""})
        assert "FSU.EDU VERIFIED" not in r.text, email
    import security
    security.login_fail_limiter.reset_all()          # that was 5 failed log-ins; the 6th would (rightly) be locked out
    r = client.post("/login/employer", data={"csrf": tok, "email": "jane@fsu.edu", "password": "x", "next": ""})
    assert "FSU.EDU VERIFIED" not in r.text and "Work email" in r.text


def test_fine_print_claims_only_what_is_true(client, monkeypatch):
    import accounts, app as appmod
    page = client.get("/login/student").text
    fine = re.search(r'<div class="vx-fine">(.*?)</div>', page).group(1)
    days = accounts.SESSION_TTL // 86400
    assert "Passwords hashed" in fine and f"{days}-day sessions" in fine and "No trackers" in fine
    assert accounts.hash_password("x").startswith("scrypt$")                       # "hashed" is true
    assert "No analytics, advertising or trackers" in client.get("/privacy").text  # "no trackers" is promised there
    for claim in ("HTTPS", "TLS", "2-STEP", "2-step", "Two-step", "NO DATA SOLD"):
        assert claim not in fine, claim                                            # not in development / not a feature here
    monkeypatch.setattr(appmod, "IS_PROD", True)
    assert appmod._vault_fine()[0] == "HTTPS"                                      # production sends HSTS


def test_sso_button_only_when_configured(client, monkeypatch):
    import sso
    for path in ("/login", "/login/student"):
        assert "single sign-on" not in client.get(path).text
    monkeypatch.setattr(sso, "enabled", lambda: True)
    st = client.get("/login/student").text
    assert 'action="/sso/start"' in st and 'class="vx-sso"' in st and "Continue with FSU single sign-on" in st
    assert 'action="/sso/start"' in client.get("/login").text
    assert "single sign-on" not in client.get("/login/employer").text


def test_every_state_page_uses_the_vault(client):
    tok = csrf_from(client.get("/signup/student").text)
    r = client.post("/signup/student", data={"email": "new@fsu.edu", "password": PW, "password2": PW, "csrf": tok, "next": "", "website": ""})
    assert r.status_code == 200 and "Check your email" in r.text and 'class="vx-card"' in r.text and "One more step" in r.text
    bad = client.get("/verify?token=nope")
    assert bad.status_code == 400 and "Link not valid" in bad.text and 'class="vx-card"' in bad.text
    assert 'class="vx-card"' in client.get("/reset?token=nope").text


def test_landing_is_the_elite_front_door(client):
    import ui, public_ui
    home = client.get("/").text
    # hero: the crest, the private-access eyebrow, the approved headline, and the two doors
    hero = home[home.index('<section class="cine"'):home.index("</section>", home.index('<section class="cine"'))]
    assert 'class="crest"' in hero and "// Florida State University · private access" in hero
    assert '<a class="primary" href="/login">Enter the vault</a>' in hero and '<a class="secondary" href="/employers">For employers</a>' in hero
    assert "Student jobs." in hero and "<em>Checked</em> for scams" in hero and 'href="/check"' in hero
    # the approved chapter headlines are still there
    assert "Not every offer" in home and "Meet employers" in home and "Then approved<br>by a <em>professional</em>" in home
    # how it works, next to a clearly labelled sample report made by the real detector
    assert 'class="px-proof"' in home and "Scan</b>" in home and "Human review</b>" in home and "Verified gallery</b>" in home
    r = ui.scan_findings()
    rep = public_ui.sample_report()
    assert "Sample report" in rep and "Made-up listing" in rep and rep in home
    assert f"<b>{r['score']}</b>" in rep and f"Matched <b>{len(r['findings'])} signals</b>" in rep and ui.esc(r["title"]) in rep
    codes = re.findall(r'<code>"(.*?)"</code>', rep)
    assert len(codes) == 3 and all(c in ui.esc(r["text"]) for c in codes)          # evidence quotes the listing verbatim
    # the scam-check teaser and the employer call to action
    assert 'class="px-check"' in home and 'href="/check?kind=message"' in home and "up to 10 checks a day" in home
    assert 'class="px-emp"' in home and 'href="/signup/employer"' in home
    import security
    assert security.public_check_limiter.max_attempts == 10                       # the teaser's "10 checks a day"
    emp = client.get("/employers").text
    assert "Enter the <em>employer</em> vault." in emp and 'href="/login/employer"' in emp and "// Employer access · verified organizations" in emp


def test_signed_in_home_is_not_the_landing(client):
    make_verified(client, "employer", "boss@acme.example")
    assert user_login(client, "employer", "boss@acme.example").status_code == 303
    assert 'class="px-proof"' not in client.get("/", follow_redirects=True).text


def test_demo_mirrors_the_public_pages():
    build = (ROOT / "demo" / "build.py").read_text()
    js = (ROOT / "demo" / "app.js").read_text()
    assert "import css_public" in build and "import public_ui" in build
    for key in ("proof", "checkTeaser", "empCta", "empVault", "vaultStudent", "vaultEmployer"):
        assert f'"{key}"' in build and f"NCS_BLOCKS.{key}" in js, key
    for name in ("P.start", "P.login", "P.signup", "P.checkmail", "P.verify", "P.forgot", "P.reset"):
        body = js[js.index(name + " = "):]
        body = body[:body.index("\nP.", 5)]
        assert "vault(" in body or "auth(" in body, name
    assert 'class="vx-card"' in js and "FSU.EDU VERIFIED" in js and "Sign in securely" in js
    import public_ui
    assert set(public_ui.SEALS) >= {"lock", "mail", "key", "check", "alert"}


def test_terms_page_is_linked_and_covers_the_key_rules(client):
    t = client.get("/terms")
    assert t.status_code == 200 and "Terms of Use" in t.text and "Last updated" in t.text
    for must in ("Third-party", "Never charge students", "not run by, sponsored by or endorsed by Florida State",
                 "not guarantees", "laws of the State of Florida", 'href="/privacy"'):
        assert must in t.text, must
    assert 'href="/terms"' in client.get("/").text                      # footer
    assert 'href="/terms"' in client.get("/signup/student").text        # agreement line on sign-up
    assert 'href="/terms"' in client.get("/privacy").text
