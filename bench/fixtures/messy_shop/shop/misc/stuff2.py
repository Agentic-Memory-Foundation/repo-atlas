"""Send a billing password reset email."""


def send_password_reset_email(address: str, token: str) -> dict:
    """Send a password reset email for a billing account."""
    return {"to": address, "template": "password-reset", "token": token}
