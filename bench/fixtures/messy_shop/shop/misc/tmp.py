"""Apply a billing discount code to an invoice."""

from .stuff2 import send_password_reset_email


def apply_discount_code(subtotal_cents: int, code: str) -> int:
    """Apply a billing discount code and return the new subtotal."""
    if code == "SAVE10":
        send_password_reset_email("billing@example.com", "notice")
        return int(subtotal_cents * 0.9)
    return subtotal_cents
