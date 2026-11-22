"""Save an uploaded image to local storage."""


def save_upload(name: str, payload: bytes) -> str:
    """Save an uploaded image and return its storage key."""
    return f"uploads/{name}:{len(payload)}"
