from __future__ import annotations

import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from erp.packages.core.config import Settings, get_settings


def action_url(purpose: str, token: str, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    base = config.api_base_url.rstrip("/") or f"http://{config.api_host}:{config.api_port}"
    route = "/activate" if purpose == "activation" else "/reset-password"
    return f"{base}{route}?{urlencode({'token': token})}"


def deliver_action_token(
    *,
    email: str,
    purpose: str,
    token: str,
    settings: Settings | None = None,
) -> bool:
    """Deliver an action link without logging or persisting the plain token.

    The plain token exists only long enough to build and send the one-time link.
    Callers must never place it in an API response or application log.
    """

    config = settings or get_settings()
    if not config.smtp_host or not config.smtp_from_email:
        return False
    link = action_url(purpose, token, config)
    subject = "Set up your ERP password" if purpose == "activation" else "Reset your ERP password"
    message = EmailMessage()
    message["From"] = config.smtp_from_email
    message["To"] = email
    message["Subject"] = subject
    message.set_content(
        f"Use this one-time link to continue: {link}\n\n"
        "The link expires automatically and can be used only once."
    )
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as client:
        if config.smtp_use_tls:
            client.starttls()
        if config.smtp_username:
            client.login(config.smtp_username, config.smtp_password)
        client.send_message(message)
    return True
