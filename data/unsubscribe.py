"""
Signed unsubscribe tokens for newsletter links.

A token is ``base64url(email).hmac`` where the HMAC is keyed by
NEWSLETTER_SECRET (falling back to ADMIN_TOKEN). The email can be read
back from the link, but a link for another address cannot be forged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os


def _secret() -> bytes:
    secret = os.environ.get("NEWSLETTER_SECRET") or os.environ.get("ADMIN_TOKEN") or ""
    if not secret:
        raise RuntimeError("NEWSLETTER_SECRET or ADMIN_TOKEN must be set to sign unsubscribe links")
    return secret.encode()


def _sign(email: str) -> str:
    digest = hmac.new(_secret(), email.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_token(email: str) -> str:
    email = email.strip().lower()
    encoded = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
    return f"{encoded}.{_sign(email)}"


def verify_token(token: str) -> str | None:
    """Return the email for a valid token, else None."""
    try:
        encoded, signature = str(token).split(".", 1)
        email = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        if hmac.compare_digest(signature, _sign(email)):
            return email
    except Exception:
        return None
    return None
