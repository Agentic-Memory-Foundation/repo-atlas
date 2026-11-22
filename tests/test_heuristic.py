from pathlib import Path

from conftest import write
from repo_atlas.config import Config
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.scan import scan_repo

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "messy_shop"


def _plan_map(root: Path, **config: object) -> dict[str, str]:
    loaded = Config(root=root, **config)  # type: ignore[arg-type]
    plan = propose_heuristic(scan_repo(root, loaded), loaded)
    return {item.path: item.proposed_path for item in plan.items}


def test_single_symbol_directory_and_skips(tmp_path: Path) -> None:
    write(
        tmp_path / "pkg" / "utils.py",
        '"""Verify Stripe webhook signatures."""\n\n'
        "def verify_stripe_webhook_signature(payload: bytes) -> bool:\n"
        "    return bool(payload)\n",
    )
    write(
        tmp_path / "pkg" / "misc" / "stuff2.py",
        '"""Send a billing password reset email."""\n\n'
        "def send_password_reset_email(address: str) -> str:\n"
        "    return address\n",
    )
    write(
        tmp_path / "pkg" / "misc" / "tmp.py",
        '"""Apply a billing discount code."""\n\n'
        "def apply_discount_code(code: str) -> bool:\n"
        "    return code == 'SAVE10'\n",
    )
    write(tmp_path / "pkg" / "misc" / "__init__.py", '"""Billing actions."""\n')
    write(tmp_path / "README.md", "keep\n")
    write(
        tmp_path / "pkg" / "create_stripe_refund.py", "def create_stripe_refund():\n    return {}\n"
    )
    mapping = _plan_map(tmp_path)
    assert mapping["pkg/utils.py"] == "pkg/verify_stripe_webhook_signature.py"
    assert mapping["pkg/misc"] == "pkg/billing"
    assert mapping["pkg/misc/stuff2.py"] == "pkg/billing/send_password_reset_email.py"
    assert "README.md" not in mapping
    assert "pkg/create_stripe_refund.py" not in mapping


def test_keyword_fallback_and_collision(tmp_path: Path) -> None:
    write(
        tmp_path / "utils.py",
        '"""Stripe webhook signature verification for billing events."""\n',
    )
    write(tmp_path / "helpers.py", "def compute_total(rows):\n    return len(rows)\n")
    write(tmp_path / "misc.py", "def compute_total(rows):\n    return sum(rows)\n")
    plan = propose_heuristic(scan_repo(tmp_path, Config(root=tmp_path)), Config(root=tmp_path))
    by_path = {item.path: item for item in plan.items}
    assert "stripe" in by_path["utils.py"].proposed_name
    assert "webhook" in by_path["utils.py"].proposed_name
    names = {by_path["helpers.py"].proposed_name, by_path["misc.py"].proposed_name}
    assert len(names) == 2
    assert any(name.startswith("compute_total") for name in names)


def test_min_confidence_drops_weak_keyword_names(tmp_path: Path) -> None:
    write(tmp_path / "utils.py", '"""Stripe webhook signature verification."""\n')
    config = Config(root=tmp_path, min_confidence=0.8)
    plan = propose_heuristic(scan_repo(tmp_path, config), config)
    assert plan.items == []


def test_fixture_names() -> None:
    config = Config(root=FIXTURE)
    plan = propose_heuristic(scan_repo(FIXTURE, config), config)
    mapping = {item.path: item.proposed_path for item in plan.items}
    assert mapping["shop/utils.py"] == "shop/verify_stripe_webhook_signature.py"
    assert mapping["shop/helpers.py"] == "shop/calculate_invoice_tax.py"
    assert mapping["shop/misc"] == "shop/billing"
    assert mapping["shop/misc/stuff2.py"] == "shop/billing/send_password_reset_email.py"
    assert mapping["shop/misc/tmp.py"] == "shop/billing/apply_discount_code.py"
    assert mapping["shop/lib"] == "shop/invoice"
    assert mapping["shop/lib/data.py"] == "shop/invoice/parse_invoice_csv.py"
    assert mapping["shop/lib/file.py"] == "shop/invoice/sum_invoice_totals.py"
    assert mapping["web/helpers.js"] == "web/calculate-cart-total.js"
    assert mapping["web/misc"] == "web/checkout"
    assert mapping["web/misc/file2.ts"] == "web/checkout/format-currency.ts"
    assert mapping["web/misc/stuff.ts"] == "web/checkout/validate-coupon-code.ts"
    assert "shop/create_stripe_refund.py" not in mapping
    assert "shop/migrations/0001_initial.py" not in mapping
    assert "tests/test_utils.py" not in mapping
    assert "manage.py" not in mapping
    assert "web/index.js" not in mapping
