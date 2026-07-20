"""
QR code utilities for verification documents.
"""

from __future__ import annotations

import base64
import io
import secrets
from urllib.parse import quote

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from django.conf import settings

from reports.exceptions import ValidationError

MIN_TOKEN_BYTES = 16
MAX_BASE_URL_LENGTH = 2048


def generate_verification_code(length: int = 20) -> str:
    """
    Generate a cryptographically secure URL-safe verification token.

    `length` represents the number of random bytes before URL-safe encoding.
    """
    if not isinstance(length, int):
        raise ValidationError("length must be an integer.")
    if length < MIN_TOKEN_BYTES:
        raise ValidationError(
            f"length must be at least {MIN_TOKEN_BYTES} bytes."
        )
    return secrets.token_urlsafe(length)


def build_verification_url(
    base_url: str,
    verification_code: str,
) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValidationError("base_url is required.")
    if (
        not isinstance(verification_code, str)
        or not verification_code.strip()
    ):
        raise ValidationError("verification_code is required.")

    base = base_url.strip().rstrip("/")
    if len(base) > MAX_BASE_URL_LENGTH:
        raise ValidationError("base_url is too long.")

    safe_code = quote(verification_code.strip(), safe="-_~")
    return f"{base}/verify/{safe_code}"


def build_default_verification_url(
    verification_code: str,
) -> str:
    base_url = getattr(settings, "REPORTS_VERIFICATION_BASE_URL", "")
    if not base_url:
        raise ValidationError(
            "REPORTS_VERIFICATION_BASE_URL is not configured."
        )
    return build_verification_url(base_url, verification_code)


def generate_qr_code_png(
    payload_url: str,
    *,
    box_size: int = 10,
    border: int = 4,
) -> bytes:
    if not isinstance(payload_url, str) or not payload_url.strip():
        raise ValidationError("payload_url is required.")

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload_url.strip())
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_qr_code_base64(
    payload_url: str,
) -> str:
    return base64.b64encode(
        generate_qr_code_png(payload_url)
    ).decode("ascii")