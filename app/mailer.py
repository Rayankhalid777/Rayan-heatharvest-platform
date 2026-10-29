"""Email through any SMTP service (Microsoft 365, Google Workspace, Zoho, SendGrid, Brevo...)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config

log = logging.getLogger("heatharvest.mail")


def configured() -> bool:
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def send(to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None,
         reply_to: str | None = None) -> bool:
    """Send one message. Returns False (and logs) when SMTP is not configured or sending fails."""
    if not configured():
        log.warning("SMTP not configured; email to %s not sent: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if attachment:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    try:
        if config.SMTP_TLS == "ssl":
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ssl.create_default_context(), timeout=30) as s:
                _login_send(s, msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
                if config.SMTP_TLS == "starttls":
                    s.starttls(context=ssl.create_default_context())
                _login_send(s, msg)
        return True
    except Exception:  # noqa: BLE001 - report any SMTP failure to the caller
        log.exception("Email to %s failed", to)
        return False


def _login_send(s, msg):
    if config.SMTP_USER:
        s.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
    s.send_message(msg)


def notify_team(subject: str, body: str) -> bool:
    if config.TEAM_NOTIFY_EMAIL:
        return send(config.TEAM_NOTIFY_EMAIL, subject, body)
    return False
