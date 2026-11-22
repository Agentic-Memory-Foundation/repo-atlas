from pathlib import Path

from repo_atlas.protect import Protection


def test_protected_categories(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n[project.scripts]\ntool = "pkg.utils:main"\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"main": "web/index.js"}', encoding="utf-8")
    rules = Protection(tmp_path, extra_globs=["keep_me/**"])
    assert rules.reason(Path("README.md")) == "protected file name"
    assert rules.reason(Path("pkg/__init__.py")) == "protected file name"
    assert rules.reason(Path("tests/test_utils.py")) == "test discovery name"
    assert rules.reason(Path("pkg/migrations/0001_initial.py")) == "framework migration"
    assert rules.reason(Path("app/dashboard/page.tsx")) == "framework convention path"
    assert rules.reason(Path("pkg/utils.py")) == "package entry point"
    assert rules.reason(Path("web/index.js")) == "protected file name"
    assert rules.reason(Path(".github/workflows/ci.yml")) == "hidden path"
    assert rules.reason(Path("keep_me/utils.py")) == "configured protected glob"
    assert rules.reason(Path("pkg/create_stripe_refund.py")) is None
    assert rules.is_structural_dir(Path("src"))
    assert not rules.is_structural_dir(Path("misc"))
