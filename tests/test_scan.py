from pathlib import Path

from conftest import write
from repo_atlas.config import Config
from repo_atlas.scan import scan_repo


def test_scan_skips_ignored_binary_vendor_and_locks(tmp_path: Path) -> None:
    write(tmp_path / ".gitignore", "ignored_vendor/\n*.pyc\n")
    write(
        tmp_path / "pkg" / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_webhook(payload: bytes) -> bool:\n    return True\n',
    )
    write(tmp_path / "ignored_vendor" / "utils.py", "def verify_webhook():\n    return False\n")
    write(tmp_path / "vendor" / "lib.py", "def verify_webhook():\n    return False\n")
    write(tmp_path / "pkg" / "cache.pyc", "not-text")
    write(tmp_path / "package-lock.json", "{}")
    write(tmp_path / "assets" / "logo.png", "not-a-real-png")
    (tmp_path / "assets" / "blob.bin").write_bytes(b"abc\x00def")
    index = scan_repo(tmp_path, Config(root=tmp_path))
    paths = {item.path.as_posix() for item in index.files}
    assert paths == {"pkg/utils.py"}
    signals = index.files[0]
    assert signals.language == "python"
    assert signals.symbols[0].name == "verify_webhook"
    assert "webhook" in signals.docstring
    reasons = {item.reason for item in index.skipped}
    assert "gitignored directory" in reasons or "gitignored file" in reasons
    assert "vendored or generated directory" in reasons
    assert "binary extension" in reasons or "binary file" in reasons
    assert "lock or generated file" in reasons


def test_javascript_signals(tmp_path: Path) -> None:
    write(
        tmp_path / "helpers.js",
        "/**\n * Calculate the shopping cart total in cents.\n */\n"
        "export function calculateCartTotal(items) {\n  return items.length;\n}\n",
    )
    index = scan_repo(tmp_path, Config(root=tmp_path))
    signals = index.files[0]
    assert signals.symbols[0].name == "calculateCartTotal"
    assert signals.symbols[0].exported
    assert "cart" in signals.docstring
