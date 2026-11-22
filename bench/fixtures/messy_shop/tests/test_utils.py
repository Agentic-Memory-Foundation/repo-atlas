from shop.utils import verify_stripe_webhook_signature


def test_signature_rejects_bad_header():
    assert verify_stripe_webhook_signature(b"{}", "bad", "secret") is False
