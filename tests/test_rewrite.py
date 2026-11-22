from pathlib import Path

from repo_atlas.rewrite import RewriteContext
from repo_atlas.rewrite.javascript import JavaScriptRewriter
from repo_atlas.rewrite.markdown import MarkdownRewriter
from repo_atlas.rewrite.python import PythonRewriter


def test_python_relative_and_absolute_imports(tmp_path: Path) -> None:
    pkg = tmp_path / "shop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def verify():\n    return True\n", encoding="utf-8")
    misc = pkg / "misc"
    misc.mkdir()
    (misc / "__init__.py").write_text("", encoding="utf-8")
    (misc / "stuff2.py").write_text("def send():\n    return 1\n", encoding="utf-8")
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("shop/__init__.py"): Path("shop/__init__.py"),
            Path("shop/utils.py"): Path("shop/verify_stripe_webhook_signature.py"),
            Path("shop/misc/__init__.py"): Path("shop/billing/__init__.py"),
            Path("shop/misc/stuff2.py"): Path("shop/billing/send_password_reset_email.py"),
            Path("shop/caller.py"): Path("shop/caller.py"),
            Path("tests/test_utils.py"): Path("tests/test_utils.py"),
        },
    )
    rewriter = PythonRewriter()
    init = "from .utils import verify\nfrom .misc.stuff2 import send\n"
    updated = rewriter.rewrite(init, Path("shop/__init__.py"), ctx)
    assert "from .verify_stripe_webhook_signature import verify" in updated
    assert "from .billing.send_password_reset_email import send" in updated
    absolute = "from shop.utils import verify\n"
    assert (
        rewriter.rewrite(absolute, Path("tests/test_utils.py"), ctx)
        == "from shop.verify_stripe_webhook_signature import verify\n"
    )
    sibling = "from .stuff2 import send\n"
    moved = rewriter.rewrite(
        sibling,
        Path("shop/misc/tmp.py"),
        RewriteContext(
            root=tmp_path,
            file_map={
                **ctx.file_map,
                Path("shop/misc/tmp.py"): Path("shop/billing/apply_discount_code.py"),
            },
        ),
    )
    assert moved == "from .send_password_reset_email import send\n"


def test_python_submodule_alias_and_dotted_import(tmp_path: Path) -> None:
    pkg = tmp_path / "shop" / "misc"
    pkg.mkdir(parents=True)
    (tmp_path / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "stuff2.py").write_text("def send():\n    return 1\n", encoding="utf-8")
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("shop/__init__.py"): Path("shop/__init__.py"),
            Path("shop/misc/__init__.py"): Path("shop/billing/__init__.py"),
            Path("shop/misc/stuff2.py"): Path("shop/billing/send_password_reset_email.py"),
            Path("app.py"): Path("app.py"),
        },
    )
    rewriter = PythonRewriter()
    aliased = rewriter.rewrite("from .misc import stuff2\n", Path("shop/__init__.py"), ctx)
    assert aliased == "from .billing import send_password_reset_email as stuff2\n"
    dotted = rewriter.rewrite(
        "import shop.misc.stuff2\n\nshop.misc.stuff2.send()\n",
        Path("app.py"),
        ctx,
    )
    assert "import shop.billing.send_password_reset_email" in dotted
    assert "shop.billing.send_password_reset_email.send()" in dotted


def test_multiline_import_keeps_names(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "utils.py").write_text("x = 1\n", encoding="utf-8")
    source = "from .utils import (\n    alpha,\n    beta,\n)\n"
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("pkg/__init__.py"): Path("pkg/__init__.py"),
            Path("pkg/utils.py"): Path("pkg/alpha_beta.py"),
        },
    )
    updated = PythonRewriter().rewrite(source, Path("pkg/__init__.py"), ctx)
    assert "from .alpha_beta import" in updated
    assert "alpha" in updated and "beta" in updated


def test_javascript_relative_imports(tmp_path: Path) -> None:
    web = tmp_path / "web"
    misc = web / "misc"
    misc.mkdir(parents=True)
    (web / "helpers.js").write_text("export function calculateCartTotal() {}\n", encoding="utf-8")
    (misc / "file2.ts").write_text("export function formatCurrency() {}\n", encoding="utf-8")
    (web / "index.js").write_text("", encoding="utf-8")
    source = (
        'import { calculateCartTotal } from "./helpers.js";\n'
        'import { formatCurrency } from "./misc/file2";\n'
        'const local = require("./helpers.js");\n'
        'const dyn = import("./helpers.js");\n'
        'import react from "react";\n'
    )
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("web/index.js"): Path("web/index.js"),
            Path("web/helpers.js"): Path("web/calculate-cart-total.js"),
            Path("web/misc/file2.ts"): Path("web/checkout/format-currency.ts"),
        },
    )
    updated = JavaScriptRewriter().rewrite(source, Path("web/index.js"), ctx)
    assert 'from "./calculate-cart-total.js"' in updated
    assert 'from "./checkout/format-currency"' in updated
    assert 'require("./calculate-cart-total.js")' in updated
    assert 'import("./calculate-cart-total.js")' in updated
    assert 'from "react"' in updated


def test_markdown_links(tmp_path: Path) -> None:
    source = "See `shop/utils.py` and [utils](shop/utils.py).\n"
    ctx = RewriteContext(
        root=tmp_path,
        file_map={Path("shop/utils.py"): Path("shop/verify_stripe_webhook_signature.py")},
        dir_map={Path("shop/misc"): Path("shop/billing")},
    )
    extra = source + "Directory `shop/misc/` moved.\n"
    updated = MarkdownRewriter().rewrite(extra, Path("docs/overview.md"), ctx)
    assert "`shop/verify_stripe_webhook_signature.py`" in updated
    assert "](shop/verify_stripe_webhook_signature.py)" in updated
    assert "`shop/billing/`" in updated
