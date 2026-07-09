import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Iterable, List

logger = logging.getLogger("cmsplus.email")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL") or SMTP_USERNAME or "cmsplus@localhost"
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in ("false", "0", "no")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


def parse_recipients(raw: str) -> List[str]:
    if not raw:
        return []
    parts = raw.replace("\n", ",").replace(";", ",").split(",")
    return [part.strip() for part in parts if part.strip()]


def send_alert_email(to_addresses: Iterable[str], subject: str, body: str) -> None:
    recipients = list(to_addresses)
    if not recipients:
        return
    if not SMTP_HOST:
        logger.warning("SMTP yapılandırılmadı (.env), e-posta gönderilmedi: %s -> %s", subject, recipients)
        return

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, recipients, message.as_string())
    except Exception:
        logger.exception("E-posta gönderilemedi: %s -> %s", subject, recipients)
