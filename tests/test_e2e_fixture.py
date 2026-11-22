import shutil
import subprocess
import sys
from pathlib import Path

from conftest import git_commit
from repo_atlas.apply import apply_plan
from repo_atlas.config import Config
from repo_atlas.mapgen import write_maps
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.scan import scan_repo
from repo_atlas.undo import latest_manifest, undo_manifest

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "messy_shop"


def test_fixture_apply_map_and_undo(tmp_path: Path) -> None:
    root = tmp_path / "messy_shop"
    shutil.copytree(FIXTURE, root)
    git_commit(root)
    config = Config(root=root)
    index = scan_repo(root, config)
    scanned = {item.path.as_posix() for item in index.files}
    assert "vendor/utils.py" not in scanned
    assert "ignored_vendor/utils.py" not in scanned
    assert "assets/logo.png" not in scanned
    plan = propose_heuristic(index, config)
    apply_plan(root, plan, files=[item.path for item in index.files], write=True)
    assert not (root / "shop" / "utils.py").exists()
    assert (root / "shop" / "verify_stripe_webhook_signature.py").is_file()
    assert (root / "shop" / "billing" / "send_password_reset_email.py").is_file()
    assert (root / "shop" / "invoice" / "parse_invoice_csv.py").is_file()
    assert (root / "web" / "calculate-cart-total.js").is_file()
    assert (root / "web" / "checkout" / "format-currency.ts").is_file()
    assert (root / "shop" / "migrations" / "0001_initial.py").is_file()
    assert (root / "shop" / "create_stripe_refund.py").is_file()
    assert (root / "tests" / "test_utils.py").is_file()
    init = (root / "shop" / "__init__.py").read_text(encoding="utf-8")
    assert "from .verify_stripe_webhook_signature import" in init
    assert "from .billing.send_password_reset_email import" in init
    assert "from .invoice.parse_invoice_csv import" in init
    assert "from .utils import" not in init
    discount = (root / "shop" / "billing" / "apply_discount_code.py").read_text(encoding="utf-8")
    assert "from .send_password_reset_email import" in discount
    index_js = (root / "web" / "index.js").read_text(encoding="utf-8")
    assert "./calculate-cart-total.js" in index_js
    assert "./checkout/format-currency" in index_js
    overview = (root / "docs" / "overview.md").read_text(encoding="utf-8")
    assert "shop/verify_stripe_webhook_signature.py" in overview
    manage = (root / "manage.py").read_text(encoding="utf-8")
    assert (
        "from shop.verify_stripe_webhook_signature import verify_stripe_webhook_signature\n"
        in manage
    )
    tests = (root / "tests" / "test_utils.py").read_text(encoding="utf-8")
    assert "shop.verify_stripe_webhook_signature" in tests
    subprocess.run(
        [sys.executable, "-c", "import shop; assert shop.verify_stripe_webhook_signature"],
        cwd=root,
        check=True,
    )
    fresh = scan_repo(root, Config(root=root))
    write_maps(root, fresh, ["agents", "claude", "cursor", "copilot", "gemini"], dry_run=False)
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- repo-atlas:start -->" in agents
    assert "shop/billing/send_password_reset_email.py" in agents
    assert (root / ".cursor" / "rules" / "repo-atlas.mdc").is_file()
    assert (root / ".github" / "copilot-instructions.md").is_file()
    assert (root / "GEMINI.md").is_file()
    assert (root / "CLAUDE.md").is_file()
    undo_manifest(root, latest_manifest(root), write=True)
    assert (root / "shop" / "utils.py").is_file()
    restored = (root / "shop" / "__init__.py").read_text(encoding="utf-8")
    assert "from .utils import verify_stripe_webhook_signature" in restored
    assert (root / "shop" / "misc" / "stuff2.py").is_file()
