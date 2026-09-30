"""FSU single sign-on (OpenID Connect against FSU's Microsoft Entra tenant), with Microsoft mocked out."""
import json, re, sqlite3, sys, time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import PW, client, csrf_from, make_verified, user_login  # noqa: E402,F401

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "app-client-id"


def _key(kid):
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key()))
    jwk.update(kid=kid, use="sig", alg="RS256")
    return k, jwk


GOOD, GOOD_JWK = _key("k1")
EVIL, _ = _key("k1")                                   # same kid, different key: a forged token


@pytest.fixture()
def fsu(client, monkeypatch):
    monkeypatch.setenv("SSO_TENANT_ID", TENANT)
    monkeypatch.setenv("SSO_CLIENT_ID", CLIENT)
    monkeypatch.setenv("SSO_CLIENT_SECRET", "not-a-real-secret")
    import sso
    state = {"claims": {}, "key": GOOD, "posted": None}
    monkeypatch.setattr(sso, "_jwks", lambda: {"keys": [GOOD_JWK]})

    def post_token(data):
        state["posted"] = data
        now = int(time.time())
        claims = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": CLIENT, "iat": now, "exp": now + 600,
                  "nonce": state["nonce"], "tid": TENANT, "email": "Evan.W@fsu.edu"} | state["claims"]
        return {"id_token": jwt.encode(claims, state["key"], algorithm="RS256", headers={"kid": "k1"})}
    monkeypatch.setattr(sso, "_post_token", post_token)
    client.sso_state = state
    return client


def _begin(c, email="evan.w@fsu.edu"):
    page = c.get("/login").text
    r = c.post("/login", data={"csrf": csrf_from(page), "email": email})
    assert "Continue to FSU single sign-on" in r.text and "Log in another way" in r.text and "never sees your FSU password" in r.text
    r = c.post("/sso/start", data={"csrf": csrf_from(r.text), "email": email, "next": ""})
    assert r.status_code == 303
    url = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "login.microsoftonline.com" and url.path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == CLIENT and q["login_hint"] == email and q["domain_hint"] == "fsu.edu" and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"].endswith("/sso/callback") and "client_secret" not in r.headers["location"]
    c.sso_state["nonce"] = q["nonce"]
    return q


def test_fsu_sign_in_creates_a_confirmed_student_and_logs_in(fsu):
    q = _begin(fsu)
    r = fsu.get(f"/sso/callback?code=abc&state={q['state']}")
    assert r.status_code == 303 and r.headers["location"] == "/profile/setup" and "usession" in r.cookies
    assert fsu.sso_state["posted"]["code_verifier"] and fsu.sso_state["posted"]["client_secret"] == "not-a-real-secret"
    with closing(sqlite3.connect(fsu.appmod.DB_PATH)) as db:
        row = db.execute("SELECT email, role, verified FROM users").fetchone()
    assert row == ("evan.w@fsu.edu", "student", 1)
    # The same state can't be replayed after the cookie is cleared.
    assert fsu.get(f"/sso/callback?code=abc&state={q['state']}").status_code == 400


@pytest.mark.parametrize("change, expect", [
    ({"state": "wrong"}, "expired or was opened in a different browser"),
    ({"claims": {"tid": "another-tenant"}}, "Couldn't finish signing in"),
    ({"claims": {"email": "someone@gmail.com"}}, "need an @fsu.edu address"),
    ({"claims": {"email": "x@fsu.edu.evil.com"}}, "need an @fsu.edu address"),
    ({"claims": {"aud": "some-other-app"}}, "Couldn't finish signing in"),
    ({"claims": {"exp": 1000}}, "Couldn't finish signing in"),
    ({"claims": {"nonce": "replayed"}}, "Couldn't finish signing in"),
    ({"key": EVIL}, "Couldn't finish signing in"),
])
def test_bad_sign_ins_are_refused(fsu, change, expect):
    q = _begin(fsu)
    fsu.sso_state["claims"] = change.get("claims", {})
    fsu.sso_state["key"] = change.get("key", GOOD)
    r = fsu.get(f"/sso/callback?code=abc&state={change.get('state', q['state'])}")
    assert r.status_code == 400 and expect in r.text and "usession" not in r.cookies
    with closing(sqlite3.connect(fsu.appmod.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_cancelled_or_missing_cookie(fsu):
    q = _begin(fsu)
    assert "cancelled" in fsu.get("/sso/callback?error=access_denied").text
    fsu.cookies.clear()
    assert fsu.get(f"/sso/callback?code=abc&state={q['state']}").status_code == 400


def test_sso_replaces_a_strangers_unconfirmed_password(fsu):
    # Someone signed the student's address up with their own password and never confirmed it.
    with closing(sqlite3.connect(fsu.appmod.DB_PATH)) as db:
        fsu.accounts.create_user(db, "evan.w@fsu.edu", "student", "Str4nger!pass")
    q = _begin(fsu)
    assert fsu.get(f"/sso/callback?code=abc&state={q['state']}").status_code == 303
    fsu.cookies.clear()
    page = fsu.get("/login/student").text
    r = fsu.post("/login/student", data={"csrf": csrf_from(page), "email": "evan.w@fsu.edu", "password": "Str4nger!pass", "next": ""})
    assert r.status_code == 401


def test_existing_student_keeps_their_account_and_password(fsu):
    make_verified(fsu, "student", "evan.w@fsu.edu")
    q = _begin(fsu)
    assert fsu.get(f"/sso/callback?code=abc&state={q['state']}").status_code == 303
    fsu.cookies.clear()
    assert user_login(fsu, "student", "evan.w@fsu.edu").status_code == 303     # password login still works too


def test_log_in_another_way_and_no_sso_without_settings(client):
    page = client.get("/login").text
    r = client.post("/login", data={"csrf": csrf_from(page), "email": "evan.w@fsu.edu"})
    assert "single sign-on" not in r.text and 'action="/login/student"' in r.text
    assert client.post("/sso/start", data={"csrf": csrf_from(page), "email": "evan.w@fsu.edu"}).headers["location"] == "/login"


def test_password_path_is_offered_when_sso_is_on(fsu):
    page = fsu.get("/login").text
    r = fsu.post("/login", data={"csrf": csrf_from(page), "email": "evan.w@fsu.edu", "how": "password"})
    assert 'action="/login/student"' in r.text and 'value="evan.w@fsu.edu"' in r.text
