"""
Email senders - Gmail SMTP (free ~500/day) and Brevo API (free 300/day).

Both implement the same tiny interface (`send`) so the outreach engine doesn't
care which one is configured. Pick via EMAIL_PROVIDER in .env.

Deliverability guardrails baked in (Section 11 / 21):
  - plain-text + light-HTML multipart (no heavy templates),
  - honest headers / real From identity,
  - the engine (not the sender) enforces daily caps + human-like delays.
"""
from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from fixgenie.common.logging_setup import get_logger

log = get_logger(__name__)


class EmailSender(ABC):
    @abstractmethod
    def send(
        self, to_email: str, to_name: str, subject: str, text_body: str, html_body: str
    ) -> tuple[bool, str]:
        """Return (success, detail). detail is a message id or an error string."""

    @abstractmethod
    def is_configured(self) -> bool:
        ...


class GmailSMTPSender(EmailSender):
    def __init__(self, address: str, app_password: str, sender_name: str) -> None:
        self.address = address
        self.app_password = app_password
        self.sender_name = sender_name

    def is_configured(self) -> bool:
        return bool(self.address and self.app_password)

    def send(self, to_email, to_name, subject, text_body, html_body):
        if not self.is_configured():
            return False, "Gmail not configured (set GMAIL_ADDRESS + GMAIL_APP_PASSWORD)"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.sender_name} <{self.address}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
        msg["Reply-To"] = self.address
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(self.address, self.app_password)
                server.send_message(msg)
            return True, "sent via Gmail SMTP"
        except smtplib.SMTPException as exc:
            return False, f"SMTP error: {exc}"


class BrevoSender(EmailSender):
    def __init__(self, api_key: str, sender_name: str, sender_email: str) -> None:
        self.api_key = api_key
        self.sender_name = sender_name
        self.sender_email = sender_email

    def is_configured(self) -> bool:
        return bool(self.api_key and self.sender_email)

    def send(self, to_email, to_name, subject, text_body, html_body):
        if not self.is_configured():
            return False, "Brevo not configured (set BREVO_API_KEY + SENDER_EMAIL)"
        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": to_email, "name": to_name or to_email}],
            "subject": subject,
            "textContent": text_body,
        }
        if html_body:
            payload["htmlContent"] = html_body
        try:
            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            if resp.status_code in (200, 201):
                return True, resp.json().get("messageId", "sent via Brevo")
            return False, f"Brevo error {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as exc:
            return False, f"Brevo request failed: {exc}"


def build_sender(settings) -> EmailSender:
    """Factory: return the configured sender based on EMAIL_PROVIDER."""
    provider = settings.email_provider
    if provider == "brevo":
        return BrevoSender(settings.brevo_api_key, settings.sender_name, settings.sender_email)
    # default: gmail
    return GmailSMTPSender(settings.gmail_address, settings.gmail_app_password, settings.sender_name)
