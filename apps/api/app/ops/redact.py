"""Redaction of stored call data. Defence in depth: the worker redacts before sending, the API
scrubs on ingest, and every read model scrubs again."""

from typing import Any

# Keys that must never be persisted or shown, wherever they appear in a payload.
FORBIDDEN_KEYS = {
    "date_of_birth",
    "dob",
    "phone",
    "phone_last4",
    "token",
    "access_token",
    "confirmation_token",
    "authorization",
    "api_key",
    "secret",
}

MAX_TEXT = 500


def scrub(value: Any) -> Any:
    """Drop forbidden keys recursively."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def safe(value: Any) -> Any:
    """Scrub and bound the size of what a read model returns."""
    cleaned = scrub(value)
    if isinstance(cleaned, str):
        return cleaned[:MAX_TEXT]
    if isinstance(cleaned, dict):
        return {k: safe(v) for k, v in list(cleaned.items())[:40]}
    if isinstance(cleaned, list):
        return [safe(v) for v in cleaned[:40]]
    return cleaned
