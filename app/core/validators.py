"""Shared field validators used by several request schemas."""

from decimal import Decimal
from urllib.parse import urlsplit

from app.config import settings

_TWO_PLACES = Decimal("0.01")

CLOUDINARY_HOST = "res.cloudinary.com"


def validate_cloudinary_url(url: str) -> str:
    """Only accept https URLs that point at *our* Cloudinary cloud.

    Stored file URLs are rendered to the counterparty and to admins, so an
    arbitrary string here is a stored-XSS / phishing vector. Restricting the
    origin also means the signed-upload flow is actually load-bearing.
    """
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("File URL must use https")
    if parts.netloc.lower() != CLOUDINARY_HOST:
        raise ValueError("File URL must be a Cloudinary URL")
    expected_prefix = f"/{settings.cloudinary_cloud_name}/"
    if not parts.path.startswith(expected_prefix):
        raise ValueError("File URL does not belong to this application")
    if len(url) > 2048:
        raise ValueError("File URL is too long")
    return url


def reject_sub_kobo(value: Decimal) -> Decimal:
    """Guard the money boundary: never more than two decimal places."""
    if value != value.quantize(_TWO_PLACES):
        raise ValueError("Amount may not have more than 2 decimal places")
    return value
