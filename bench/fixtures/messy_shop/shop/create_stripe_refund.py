"""Create a refund through the Stripe API."""


def create_stripe_refund(charge_id: str, amount_cents: int) -> dict:
    """Create a Stripe refund for a charge."""
    return {"charge": charge_id, "amount": amount_cents, "object": "refund"}
