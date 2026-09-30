"""
FSU single sign-on for students, the way Handshake does it: type your @fsu.edu address, press
"Continue to FSU single sign-on", sign in on FSU's own Microsoft page (with Duo), come back
logged in. NoleCareerShield never sees the student's FSU password.

It is standard OpenID Connect (authorization code + PKCE) against FSU's Microsoft Entra ID
tenant. It only switches on when all three settings are present in the host's environment,
never in the code or in git:

    SSO_TENANT_ID      FSU's Entra tenant ID (from FSU ITS)
    SSO_CLIENT_ID      the app registration's client ID
    SSO_CLIENT_SECRET  the app registration's client secret

FSU ITS has to register NoleCareerShield as an app in their tenant with the redirect URI
{BASE_URL}/sso/callback. Until they do, the button isn't shown and students log in with
email and password as before.

What is checked on the way back: the state and nonce this browser was given, the ID token's
signature (Microsoft's published keys), issuer, audience, expiry and tenant, and that the
signed-in address is exactly @fsu.edu.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from urllib.parse import urlencode

import httpx

import accounts
import security

COOKIE = "sso"
COOKIE_TTL = 10 * 60
NAME = os.environ.get("SSO_NAME", "FSU")
TIMEOUT = 10.0


def _cfg() -> dict:
    return {"tenant": os.environ.get("SSO_TENANT_ID", "").strip(), "client_id": os.environ.get("SSO_CLIENT_ID", "").strip(),
            "secret": os.environ.get("SSO_CLIENT_SECRET", "").strip()}


def enabled() -> bool:
    c = _cfg()
    return all(c.values())


def _base() -> str:
    return f"https://login.microsoftonline.com/{_cfg()['tenant']}"


def redirect_uri() -> str:
    return security.BASE_URL + "/sso/callback"


# ---------- the signed, short-lived cookie that carries state between the two legs ----------

def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(security.secret_key(), ("sso|" + raw).encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _unsign(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(security.secret_key(), ("sso|" + raw).encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or time.time() - float(data.get("ts", 0)) > COOKIE_TTL:
        return None
    return data


def start(email: str, next_: str) -> tuple[str, str]:
    """(URL of FSU's sign-in page, cookie value)."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {"client_id": _cfg()["client_id"], "response_type": "code", "redirect_uri": redirect_uri(), "response_mode": "query",
              "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
              "code_challenge_method": "S256", "domain_hint": accounts.STUDENT_DOMAIN}
    if email:
        params["login_hint"] = email
    cookie = _sign({"state": state, "nonce": nonce, "verifier": verifier, "next": next_, "ts": time.time()})
    return f"{_base()}/oauth2/v2.0/authorize?{urlencode(params)}", cookie


# ---------- network calls (replaced in tests) ----------

def _post_token(data: dict) -> dict:
    r = httpx.post(f"{_base()}/oauth2/v2.0/token", data=data, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


_jwks_cache: dict = {"at": 0.0, "keys": None}


def _jwks() -> dict:
    if not _jwks_cache["keys"] or time.time() - _jwks_cache["at"] > 3600:
        r = httpx.get(f"{_base()}/discovery/v2.0/keys", timeout=TIMEOUT)
        r.raise_for_status()
        _jwks_cache.update(at=time.time(), keys=r.json())
    return _jwks_cache["keys"]


class SSOError(Exception):
    pass


def finish(code: str, state: str, cookie: str | None) -> tuple[str, str]:
    """Completes the sign-in. Returns (verified @fsu.edu email, next). Raises SSOError."""
    import jwt  # PyJWT, only needed when SSO is on

    saved = _unsign(cookie)
    if not saved or not state or not hmac.compare_digest(saved["state"], state):
        raise SSOError("That sign-in link expired or was opened in a different browser. Please start again.")
    if not code or len(code) > 4000:
        raise SSOError("FSU didn't send a sign-in code back. Please start again.")
    c = _cfg()
    try:
        tok = _post_token({"client_id": c["client_id"], "client_secret": c["secret"], "grant_type": "authorization_code", "code": code,
                           "redirect_uri": redirect_uri(), "code_verifier": saved["verifier"], "scope": "openid email profile"})
        id_token = tok["id_token"]
        kid = jwt.get_unverified_header(id_token).get("kid")
        key = next((k for k in _jwks().get("keys", []) if k.get("kid") == kid), None)
        if not key:
            raise SSOError("Couldn't check FSU's sign-in. Please try again.")
        claims = jwt.decode(id_token, jwt.PyJWK(key).key, algorithms=["RS256"], audience=c["client_id"],
                            issuer=f"{_base()}/v2.0", options={"require": ["exp", "iat", "aud", "iss", "nonce"]}, leeway=60)
    except SSOError:
        raise
    except Exception as e:  # noqa: BLE001 - network, JSON or token problems all mean "didn't work"
        raise SSOError("Couldn't finish signing in with FSU. Please try again, or log in another way.") from e
    if not hmac.compare_digest(str(claims.get("nonce", "")), saved["nonce"]) or claims.get("tid") != c["tenant"]:
        raise SSOError("Couldn't finish signing in with FSU. Please try again, or log in another way.")
    raw = claims.get("email") or claims.get("preferred_username") or claims.get("upn") or ""
    try:
        email = accounts.normalize_email(raw)
    except ValueError as e:
        raise SSOError("Your FSU account didn't share an email address.") from e
    if not accounts.is_fsu_email(email):
        raise SSOError("Student accounts need an @fsu.edu address.")
    return email, saved.get("next") or ""


def user_for(db: sqlite3.Connection, email: str) -> dict:
    """The student account for a verified FSU address, created on first sign-in. FSU already proved the address,
    so it counts as confirmed; the random password is never shown, so this account only signs in through FSU
    until the student sets a password with "Forgot password"."""
    u = accounts.get_user(db, email, "student")
    if not u:
        accounts.create_user(db, email, "student", secrets.token_urlsafe(32) + "Aa1!")
        u = accounts.get_user(db, email, "student")
    if not u["verified"]:
        # Someone may have signed this address up earlier without confirming it. FSU just proved who owns it,
        # so that stranger's password is replaced before the account is confirmed.
        accounts.set_password(db, u["id"], secrets.token_urlsafe(32) + "Aa1!")
        accounts.mark_verified(db, u["id"])
        u = accounts.get_user(db, email, "student")
    return u
