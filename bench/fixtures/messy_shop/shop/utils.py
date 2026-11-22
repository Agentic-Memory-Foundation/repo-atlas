"""Verify Stripe webhook signatures using the endpoint secret."""

import hashlib
import hmac


def verify_stripe_webhook_signature(payload: bytes, header: str, secret: str) -> bool:
    """Return True when the Stripe signature header matches the payload."""
    if not header.startswith("t="):
        return False
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header.split(",")[-1])
