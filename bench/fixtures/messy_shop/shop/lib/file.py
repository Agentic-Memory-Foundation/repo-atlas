"""Sum invoice totals across CSV rows."""


def sum_invoice_totals(rows: list[dict]) -> int:
    """Sum invoice totals in cents."""
    return sum(int(row["total"]) for row in rows)
