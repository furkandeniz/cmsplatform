import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.x509.oid import NameOID

from app.models import Environment


def _reset_ssl_fields(environment: Environment, checked_at: datetime, error: str) -> None:
    environment.ssl_checked_at = checked_at
    environment.ssl_ok = False
    environment.ssl_expires_at = None
    environment.ssl_days_remaining = None
    environment.ssl_issuer = None
    environment.ssl_subject = None
    environment.ssl_error = error


def run_ssl_check(environment: Environment) -> None:
    checked_at = datetime.now(timezone.utc)
    parsed = urlparse(environment.url)
    hostname = parsed.hostname
    port = parsed.port or 443

    if parsed.scheme != "https" or not hostname:
        _reset_ssl_fields(environment, checked_at, "Ortam URL'si https değil")
        return

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                der_cert = ssock.getpeercert(binary_form=True)

        cert = x509.load_der_x509_certificate(der_cert)
        not_before = cert.not_valid_before_utc
        not_after = cert.not_valid_after_utc

        issuer_cn = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        issuer_name = issuer_cn[0].value if issuer_cn else cert.issuer.rfc4514_string()
        subject_cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        subject_name = subject_cn[0].value if subject_cn else cert.subject.rfc4514_string()

        is_valid_now = not_before <= checked_at <= not_after

        environment.ssl_checked_at = checked_at
        environment.ssl_ok = is_valid_now
        environment.ssl_expires_at = not_after
        environment.ssl_days_remaining = (not_after - checked_at).days
        environment.ssl_issuer = str(issuer_name)[:255]
        environment.ssl_subject = str(subject_name)[:255]
        environment.ssl_error = None if is_valid_now else "Sertifikanın süresi dolmuş"
    except Exception as exc:
        _reset_ssl_fields(environment, checked_at, str(exc)[:255])
