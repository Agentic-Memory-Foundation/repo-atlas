"""Calculate invoice tax for a billing period."""


def calculate_invoice_tax(subtotal_cents: int, rate: float) -> int:
    """Calculate invoice tax in cents from a subtotal and a tax rate."""
    return round(subtotal_cents * rate)
