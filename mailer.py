"""
Outgoing email.

Production: set SMTP_HOST, SMTP_FROM (and SMTP_USER / SMTP_PASSWORD if your provider
needs them). SMTP_PORT defaults to 587 with STARTTLS; set SMTP_SSL=1 to use implicit
TLS (port 465). Any provider that offers SMTP works: Postmark, SendGrid, Mailgun,
Amazon SES, Resend, a university relay.

Development (no SMTP_HOST): nothing is sent. Each message is kept in `outbox` and
appended to OUTBOX_LOG (default outbox.log) so you can copy the confirmation link.
Production refuses to start without SMTP settings, so this can never silently
swallow real users' confirmation emails.

Messages are plain text with no tracking pixels and no tracked links.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import time
from email.message import EmailMessage

log = logging.getLogger("nolecareershield.mail")

outbox: list[dict] = []          # development / tests only
copy_hook = None                 # set by the app: keeps an in-site copy for account holders (emails.py)


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST", "").strip() and os.environ.get("SMTP_FROM", "").strip())


def send(to: str, subject: str, body: str) -> None:
    """Send one message. Never raises: a mail outage must not break a page or reveal whether an account exists."""
    if copy_hook:
        try:
            copy_hook(to, subject, body)
        except Exception:                  # noqa: BLE001 - the copy is a convenience, never a reason to fail
            log.exception("could not keep an in-site copy")
    try:
        if not smtp_configured():
            entry = {"to": to, "subject": subject, "body": body, "at": time.time()}
            outbox.append(entry)
            path = os.environ.get("OUTBOX_LOG", "outbox.log")
            if path:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            log.info("dev mail to %s: %s", to, subject)
            return
        msg = EmailMessage()
        msg["From"] = os.environ["SMTP_FROM"].strip()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        host = os.environ["SMTP_HOST"].strip()
        use_ssl = os.environ.get("SMTP_SSL", "0") == "1"
        port = int(os.environ.get("SMTP_PORT", "465" if use_ssl else "587"))
        ctx = ssl.create_default_context()
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=ctx)
        with server:
            user = os.environ.get("SMTP_USER", "")
            if user:
                server.login(user, os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
    except Exception:                      # noqa: BLE001 - see docstring
        log.exception("could not send mail to %s", to)
