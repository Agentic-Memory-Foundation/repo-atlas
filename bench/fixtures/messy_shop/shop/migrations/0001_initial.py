"""Initial billing tables."""


def apply_migration() -> list[str]:
    return ["create table invoice(id int)"]
