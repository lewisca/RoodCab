"""Hand (action): deliver the referral by EMAIL.

Referrals go to the client's email already on file in DisputeFox (ClientScore.email).
We do NOT send SMS.

  * ConsoleSender    -- dry-run; prints the exact email that would be sent.
  * SMTPEmailSender  -- real delivery via any SMTP relay (SendGrid/SES/Mailgun/Postmark/...).

build_sender() returns ConsoleSender while DRY_RUN is true (safe preview) and the real
SMTP sender once DRY_RUN=false. Email copy is CAN-SPAM shaped: every message carries an
unsubscribe link + a physical postal address. PII note: the recipient address is used
in-flight only and is never written to Memory.
"""
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

import config


class Sender(ABC):
    @abstractmethod
    def send(self, client, message) -> bool: ...


def _footer():
    """CAN-SPAM footer appended to every email body."""
    return (f"\n\n{config.CONSENT_LINE}\n"
            f"Unsubscribe: {config.UNSUBSCRIBE_URL}\n{config.PHYSICAL_ADDRESS}")


def compose(client, message):
    """Build (subject, full_body) for the outbound email."""
    return config.EMAIL_SUBJECT, message + _footer()


class ConsoleSender(Sender):
    """Dry-run: prints the email exactly as it would be sent. Nothing leaves the machine."""
    def send(self, client, message):
        subject, body = compose(client, message)
        print(f"\n--- WOULD EMAIL -> {client.name} <{client.email}> ---\n"
              f"Subject: {subject}\n\n{body}\n{'-' * 48}")
        return True


class SMTPEmailSender(Sender):
    """Real email via SMTP. Configure SMTP_* + FROM_EMAIL in the environment."""
    def __init__(self, host=None, port=None, user=None, password=None,
                 from_email=None, from_name=None, starttls=None):
        self.host = config.SMTP_HOST if host is None else host
        self.port = config.SMTP_PORT if port is None else port
        self.user = config.SMTP_USER if user is None else user
        self.password = config.SMTP_PASSWORD if password is None else password
        self.from_email = from_email or config.FROM_EMAIL
        self.from_name = from_name or config.FROM_NAME
        self.starttls = config.SMTP_STARTTLS if starttls is None else starttls

    def build_email(self, client, message):
        """Construct the EmailMessage (separated from transport so it's testable)."""
        if not (client.email or "").strip():
            raise ValueError(f"client {client.client_id} has no email address on file")
        subject, body = compose(client, message)
        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = client.email
        msg["Subject"] = subject
        msg["List-Unsubscribe"] = f"<{config.UNSUBSCRIBE_URL}>"   # one-click opt-out
        msg.set_content(body)
        return msg

    def send(self, client, message):
        if not self.host:
            raise RuntimeError(
                "SMTPEmailSender not configured. Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD "
                "(and FROM_EMAIL) for your email provider's SMTP relay."
            )
        msg = self.build_email(client, message)
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)
        return True


def build_sender():
    """DRY_RUN -> ConsoleSender (safe preview). Live -> the configured real sender."""
    if config.DRY_RUN:
        return ConsoleSender()
    if config.SENDER == "smtp":
        return SMTPEmailSender()
    if config.SENDER == "console":
        return ConsoleSender()
    raise RuntimeError(f"Unknown SENDER={config.SENDER!r} (expected 'smtp' or 'console').")
