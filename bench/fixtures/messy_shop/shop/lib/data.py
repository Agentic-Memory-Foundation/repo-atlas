"""Parse invoice CSV rows exported by the billing system."""


def parse_invoice_csv(text: str) -> list[dict]:
    """Parse invoice CSV rows into dictionaries."""
    rows = []
    for line in text.splitlines():
        invoice_id, total = line.split(",")
        rows.append({"invoice_id": invoice_id, "total": int(total)})
    return rows
