"""Vendored copy that must not be scanned."""


def verify_stripe_webhook_signature(payload, header, secret):
    return False
