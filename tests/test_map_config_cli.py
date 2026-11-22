import json
from pathlib import Path

import pytest

from conftest import git_commit, write
from repo_atlas.cli import main
from repo_atlas.config import Config, load_config
from repo_atlas.mapgen import detect_tools, render_map_body, upsert_managed, write_maps
from repo_atlas.scan import scan_repo


def test_managed_section_preserves_user_text(tmp_path: Path) -> None:
    existing = (
        "# Notes\n\n"
        "Keep this paragraph.\n\n"
        "<!-- repo-atlas:start -->\n"
        "old map\n"
        "<!-- repo-atlas:end -->\n"
        "\n"
        "## More\n\n"
        "Also keep this.\n"
    )
    updated = upsert_managed(existing, "## Feature map\n\n- `pkg/verify.py`: Verify signatures.\n")
    assert updated.startswith("# Notes\n\nKeep this paragraph.")
    assert "Also keep this." in updated
    assert "old map" not in updated
    assert "pkg/verify.py" in updated
    again = upsert_managed(updated, "## Feature map\n\n- `pkg/other.py`: Other.\n")
    assert "Keep this paragraph." in again
    assert "Also keep this." in again
    assert "pkg/verify.py" not in again
    assert "pkg/other.py" in again


def test_map_writes_selected_tools(tmp_path: Path) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify Stripe webhook signatures."""\n\ndef verify_stripe_webhook_signature():\n    return True\n',
    )
    write(tmp_path / "CLAUDE.md", "# Custom\n\nDo not delete me.\n")
    index = scan_repo(tmp_path, Config(root=tmp_path))
    body = render_map_body(index)
    assert "verify_stripe_webhook_signature.py" not in body
    assert "utils.py" in body
    assert "Verify Stripe webhook signatures" in body
    paths = write_maps(tmp_path, index, ["agents", "claude", "cursor"], dry_run=False)
    assert (tmp_path / "AGENTS.md").is_file()
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Do not delete me." in claude
    assert "<!-- repo-atlas:start -->" in claude
    assert (tmp_path / ".cursor" / "rules" / "repo-atlas.mdc").is_file()
    assert detect_tools(tmp_path) == ["agents", "claude", "cursor"]
    assert len(paths) == 3


def test_config_file_and_environment(tmp_path: Path, monkeypatch) -> None:
    write(
        tmp_path / "pyproject.toml",
        '[tool.repo-atlas]\nbackend = "none"\nmin_confidence = 0.4\n'
        'exclude = ["skip/**"]\n\n[tool.repo-atlas.local]\nmodel = "from-pyproject"\n',
    )
    write(
        tmp_path / "repo-atlas.toml",
        'backend = "local"\nprotected = ["secret/**"]\n\n[local]\nmodel = "from-toml"\n',
    )
    monkeypatch.setenv("REPO_ATLAS_LOCAL_MODEL", "from-env")
    config = load_config(tmp_path)
    assert config.backend == "local"
    assert config.min_confidence == 0.4
    assert config.exclude == ["skip/**"]
    assert config.protected == ["secret/**"]
    assert config.local_model == "from-env"


def test_cli_propose_apply_and_map(git_repo: Path, capsys) -> None:
    write(
        git_repo / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    git_commit(git_repo)
    assert main(["scan", str(git_repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"][0]["path"] == "utils.py"
    plan_path = git_repo / "plan.json"
    assert (
        main(["propose", str(git_repo), "--backend", "none", "-o", str(plan_path), "--json"]) == 0
    )
    capsys.readouterr()
    assert plan_path.is_file()
    assert main(["apply", str(plan_path)]) == 0
    dry = capsys.readouterr().out
    assert "Dry run" in dry
    assert (git_repo / "utils.py").is_file()
    assert main(["apply", str(plan_path), "--write"]) == 0
    assert (git_repo / "verify_signature.py").is_file()
    assert main(["map", str(git_repo), "--tools", "agents", "--stdout"]) == 0
    text = (git_repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- repo-atlas:start -->" in text
    assert "verify_signature.py" in text
    assert main(["undo", "--root", str(git_repo)]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert main(["undo", "--root", str(git_repo), "--write"]) == 0
    assert (git_repo / "utils.py").is_file()
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
