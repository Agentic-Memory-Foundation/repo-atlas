"""Extra paths for languages, config errors, backends, and the CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from conftest import git_commit, write
from repo_atlas.apply import apply_plan
from repo_atlas.cli import app, main
from repo_atlas.config import Config, find_project_root, load_config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.mapgen import parse_tool_list
from repo_atlas.naming import (
    build_filename,
    first_sentence,
    naming_style_for,
    valid_directory_name,
)
from repo_atlas.plan import load_plan, plan_from_json
from repo_atlas.propose.agent import build_agent_pack, ingest_agent_file, ingest_agent_plan
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.propose.llm import parse_model_json, propose_llm
from repo_atlas.protect import Protection
from repo_atlas.rewrite.base import RewriteContext
from repo_atlas.rewrite.javascript import JavaScriptRewriter
from repo_atlas.rewrite.python import PythonRewriter
from repo_atlas.scan import MAX_FILE_BYTES, scan_repo
from repo_atlas.signals import extract_signals
from repo_atlas.undo import latest_manifest, load_manifest, undo_manifest


def test_extract_other_languages(tmp_path: Path) -> None:
    samples = {
        "lib.go": "func Serve() {}\nfunc (s *Box) Run() {}\n",
        "lib.rs": "pub fn run() {}\nfn hidden() {}\npub struct Item {}\n",
        "lib.rb": "def self.ping\nend\n",
        "Lib.java": "public static void run() {}\n",
        "notes.md": "# Invoice tax\n\nDetails.\n",
        "notes.txt": "# a comment\n// another\n",
        "bad.py": "def (\n",
        "consts.py": '"""Module."""\n\nLIMIT: int = 3\nNAME = "x"\n# keep\n',
        "helpers.js": (
            "export const answer = 1;\n"
            "export { answer as total }\n"
            "function localHelper() {}\n"
            "// line note\n"
        ),
    }
    for name, source in samples.items():
        signals = extract_signals(Path(name), source)
        assert signals.language
        assert signals.to_summary()["language"] == signals.language
    long = extract_signals(Path("big.py"), "x" * 5000)
    assert len(long.excerpt) < 5000
    go = extract_signals(Path("lib.go"), samples["lib.go"])
    assert any(symbol.name == "Serve" for symbol in go.symbols)
    rust = extract_signals(Path("lib.rs"), samples["lib.rs"])
    assert any(symbol.name == "Item" for symbol in rust.symbols)
    md = extract_signals(Path("notes.md"), samples["notes.md"])
    assert md.docstring == "Invoice tax"
    text = extract_signals(Path("notes.txt"), samples["notes.txt"])
    assert text.comments


def test_naming_edges() -> None:
    assert naming_style_for("typescript", "camel") == "camel"
    camel = build_filename(["calculate", "cart", "total"], ".ts", "typescript", "camel")
    assert camel == "calculateCartTotal.ts"
    long_name = build_filename(["token"] * 20, ".py", "python", "auto")
    assert long_name is not None
    assert len(Path(long_name).stem) <= 60
    assert valid_directory_name("billing", True)
    assert not valid_directory_name("123bad", True)
    assert first_sentence("Hello world. More text.") == "Hello world"
    assert first_sentence("word " * 40).endswith("...")


def test_config_validation_and_aliases(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(RepoAtlasError):
        Config(backend="nope").validate()
    with pytest.raises(RepoAtlasError):
        Config(naming_style="title").validate()
    with pytest.raises(RepoAtlasError):
        Config(min_confidence=2).validate()
    with pytest.raises(RepoAtlasError):
        Config(batch_size=0).validate()
    write(
        tmp_path / "pyproject.toml",
        '[tool.repo-atlas]\nnaming = "kebab"\ninclude = "pkg/**"\n'
        "timeout_seconds = 5\nbatch_size = 2\n\n"
        '[tool.repo-atlas.api]\nbase_url = "https://example.invalid/v1"\n'
        'model = "demo"\napi_key_env = "CUSTOM_KEY"\n',
    )
    monkeypatch.setenv("REPO_ATLAS_API_BASE_URL", "https://override.invalid/v1")
    monkeypatch.setenv("REPO_ATLAS_API_MODEL", "override-model")
    monkeypatch.setenv("REPO_ATLAS_LOCAL_BASE_URL", "http://127.0.0.1:9/v1")
    config = load_config(tmp_path)
    assert config.naming_style == "kebab"
    assert config.include == ["pkg/**"]
    assert config.api_model == "override-model"
    assert config.batch_size == 2
    write(tmp_path / "repo-atlas.toml", "include = 3\n")
    with pytest.raises(RepoAtlasError):
        load_config(tmp_path)
    marker = tmp_path / "nested" / "file.py"
    write(marker, "x = 1\n")
    assert find_project_root(marker) == tmp_path.resolve() or find_project_root(marker).exists()


def test_protection_entrypoints_and_alembic(tmp_path: Path) -> None:
    write(tmp_path / "package.json", "{")
    write(
        tmp_path / "pyproject.toml",
        '[project.scripts]\ntool = "src.pkg.cli:main"\n',
    )
    rules = Protection(tmp_path)
    assert rules.reason(Path("src/pkg/cli.py")) == "package entry point"
    assert rules.reason(Path("alembic/versions/0001_init.py")) == "framework migration"
    write(tmp_path / "package.json", '{"bin": {"tool": "bin/tool.js"}, "module": "web/mod.js"}')
    rules = Protection(tmp_path)
    assert rules.reason(Path("bin/tool.js")) == "package entry point"


def test_scan_include_exclude_and_limits(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path / "pkg" / "keep.py", "def keep():\n    return 1\n")
    write(tmp_path / "skip" / "utils.py", "def skip():\n    return 1\n")
    write(tmp_path / "link.py", "def linked():\n    return 1\n")
    target = tmp_path / "pkg" / "keep.py"
    link = tmp_path / "alias.py"
    link.symlink_to(target)
    monkeypatch.setattr("repo_atlas.scan.MAX_FILE_BYTES", 30)
    write(tmp_path / "pkg" / "huge.py", "def huge():\n    return " + ("1" * 80) + "\n")
    config = Config(root=tmp_path, exclude=["skip/**"], include=["pkg/**", "alias.py"])
    index = scan_repo(tmp_path, config)
    paths = {item.path.as_posix() for item in index.files}
    assert "pkg/keep.py" in paths
    assert "skip/utils.py" not in paths
    assert "alias.py" not in paths
    assert any(item.reason == "symlink" for item in index.skipped)
    assert any(item.reason == "file too large" for item in index.skipped)
    assert MAX_FILE_BYTES > 30


def test_multi_symbol_and_agent_directory(tmp_path: Path) -> None:
    write(
        tmp_path / "helpers.py",
        '"""Calculate invoice tax for a period."""\n\n'
        "def calculate_invoice_tax(cents: int) -> int:\n    return cents\n\n"
        "def format_invoice_number(seq: int) -> str:\n    return str(seq)\n",
    )
    write(
        tmp_path / "misc" / "stuff2.py",
        '"""Send a billing password reset email."""\n\n'
        "def send_password_reset_email() -> None:\n    return None\n",
    )
    write(
        tmp_path / "misc" / "tmp.py",
        '"""Apply a billing discount code."""\n\n'
        "def apply_discount_code() -> None:\n    return None\n",
    )
    write(tmp_path / "tests" / "test_utils.py", "def test_utils():\n    assert True\n")
    config = Config(root=tmp_path)
    index = scan_repo(tmp_path, config)
    plan = propose_heuristic(index, config)
    helpers = next(item for item in plan.items if item.path == "helpers.py")
    assert helpers.confidence < 0.91
    assert "invoice" in helpers.proposed_name
    draft, _prompt = build_agent_pack(index, config)
    directory = next(item for item in draft.items if item.kind == "directory")
    directory.proposed_name = "billing"
    directory.confidence = 0
    directory.reason = ""
    file_item = next(item for item in draft.items if item.path == "misc/stuff2.py")
    file_item.proposed_name = "send_password_reset_email.py"
    file_item.confidence = 0.8
    file_item.reason = "Password reset email."
    empty = next(item for item in draft.items if item.path == "misc/tmp.py")
    empty.proposed_name = ""
    ingested = ingest_agent_plan(draft, index, config)
    assert any(item.proposed_name == "billing" for item in ingested.items)
    assert any(item.confidence == 0.75 for item in ingested.items)
    bad = next(item for item in draft.items if item.path == "helpers.py")
    bad.proposed_name = "still_helpers.txt"
    bad.confidence = 0.9
    with pytest.raises(RepoAtlasError):
        ingest_agent_plan(draft, index, config)
    bad.proposed_name = "still_helpers.py"
    bad.confidence = 1.4
    with pytest.raises(RepoAtlasError):
        ingest_agent_plan(draft, index, config)
    from repo_atlas.plan import PlanItem

    draft.items.append(
        PlanItem(
            path="../escape.py",
            kind="file",
            language="python",
            current_name="escape.py",
            proposed_name="escape.py",
            proposed_path="",
            reason="nope",
            confidence=0.9,
        )
    )
    with pytest.raises(RepoAtlasError):
        ingest_agent_plan(draft, index, config)


def test_llm_errors_and_api_header(tmp_path: Path, monkeypatch) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify Stripe webhook signatures."""\n\ndef verify_stripe_webhook_signature():\n    return True\n',
    )
    write(
        tmp_path / "misc" / "a.py",
        '"""Send a billing email."""\n\ndef send_billing_email():\n    return 1\n',
    )
    write(
        tmp_path / "misc" / "b.py",
        '"""Apply a billing credit."""\n\ndef apply_billing_credit():\n    return 1\n',
    )
    config = Config(root=tmp_path)
    index = scan_repo(tmp_path, config)
    assert "renames" in parse_model_json('```json\n{"renames": []}\n```')

    def bad_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1]"}}]})

    plan = propose_llm(
        index,
        config,
        backend="local",
        client=httpx.Client(transport=httpx.MockTransport(bad_json)),
    )
    assert plan.warnings

    def missing_shape(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(RepoAtlasError):
        propose_llm(
            index,
            config,
            backend="local",
            client=httpx.Client(transport=httpx.MockTransport(missing_shape)),
        )

    def http_error(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(RepoAtlasError):
        propose_llm(
            index,
            config,
            backend="local",
            client=httpx.Client(transport=httpx.MockTransport(http_error)),
        )

    def api_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        body = json.dumps(
            {
                "renames": [
                    {
                        "path": "utils.py",
                        "proposed_name": "nope.txt",
                        "reason": "wrong extension",
                        "confidence": 0.9,
                    },
                    {
                        "path": "misc",
                        "kind": "directory",
                        "proposed_name": "billing",
                        "reason": "Shared billing work.",
                        "confidence": 0.8,
                    },
                ]
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    monkeypatch.setenv("REPO_ATLAS_API_KEY", "secret")
    api_plan = propose_llm(
        index,
        config,
        backend="api",
        client=httpx.Client(transport=httpx.MockTransport(api_handler)),
    )
    assert api_plan.backend == "api"
    assert any(item.proposed_name == "billing" for item in api_plan.items)
    assert any("Ignored an invalid model name" in warning for warning in api_plan.warnings)


def test_rewriter_edges(tmp_path: Path) -> None:
    write(tmp_path / "pkg" / "__init__.py", "")
    write(tmp_path / "pkg" / "utils.py", "VALUE = 1\n")
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("pkg/utils.py"): Path("pkg/limit_value.py"),
            Path("app.py"): Path("app.py"),
        },
    )
    updated = PythonRewriter().rewrite(
        "import pkg.utils as helpers\n",
        Path("app.py"),
        ctx,
    )
    assert "import pkg.limit_value as helpers" in updated
    assert PythonRewriter().rewrite("def (\n", Path("app.py"), ctx) == "def (\n"
    source = '// from "./helpers.js"\nimport x from "react";\n'
    js = JavaScriptRewriter().rewrite(
        source,
        Path("web/index.js"),
        RewriteContext(root=tmp_path, file_map={}),
    )
    assert js == source


def test_apply_and_undo_errors(tmp_path: Path) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    config = Config(root=tmp_path)
    index = scan_repo(tmp_path, config)
    plan = propose_heuristic(index, config)
    with pytest.raises(RepoAtlasError):
        apply_plan(tmp_path, plan, files=[item.path for item in index.files], write=True)
    with pytest.raises(RepoAtlasError):
        latest_manifest(tmp_path)
    write(tmp_path / "manifest.json", "{")
    with pytest.raises(RepoAtlasError):
        load_manifest(tmp_path / "manifest.json")
    with pytest.raises(RepoAtlasError):
        plan_from_json("[]")
    with pytest.raises(RepoAtlasError):
        load_plan(tmp_path / "missing.json")


def test_cli_remaining_commands(tmp_path: Path, monkeypatch, capsys) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    write(
        tmp_path / "misc" / "a.py",
        '"""Send a billing email."""\n\ndef send_billing_email():\n    return 1\n',
    )
    write(
        tmp_path / "misc" / "b.py",
        '"""Apply a billing credit."""\n\ndef apply_billing_credit():\n    return 1\n',
    )
    assert main(["scan", str(tmp_path)]) == 0
    assert "utils.py" in capsys.readouterr().out
    pack = tmp_path / "pack.json"
    assert main(["propose", str(tmp_path), "--backend", "agent", "-o", str(pack)]) == 0
    assert pack.is_file()
    assert pack.with_name("PROMPT.md").is_file()
    assert main(["propose", str(tmp_path), "--backend", "agent"]) == 0
    assert (tmp_path / "repo-atlas-agent-pack" / "plan.json").is_file()
    draft = load_plan(pack)
    for item in draft.items:
        if item.kind == "file" and item.path == "utils.py":
            item.proposed_name = "verify_signature.py"
            item.reason = "Webhook signatures."
            item.confidence = 0.9
        elif item.kind == "directory":
            item.proposed_name = "billing"
            item.reason = "Billing helpers."
            item.confidence = 0.8
    pack.write_text(json.dumps(_plan_dict(draft)), encoding="utf-8")
    out = tmp_path / "ready.json"
    assert main(["ingest", str(pack), "-o", str(out), "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["apply", str(out), "--json", "--no-git", "--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert main(["apply", str(out), "--write", "--no-git", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "verify_signature.py").is_file()
    assert main(["map", str(tmp_path), "--tools", "all", "--dry-run"]) == 0
    assert main(["map", str(tmp_path), "--tools", "not-a-tool"]) == 1
    assert "agents" in parse_tool_list("all", tmp_path)
    monkeypatch.setattr(sys, "argv", ["repo-atlas", "scan", str(tmp_path)])
    with pytest.raises(SystemExit) as caught:
        app()
    assert caught.value.code == 0


def _plan_dict(plan) -> dict:
    from repo_atlas.plan import plan_to_json

    return json.loads(plan_to_json(plan))


def test_git_undo_plan_and_backend_flags(tmp_path: Path, monkeypatch) -> None:
    from repo_atlas.gitutil import dirty_entries, ensure_clean, run_git
    from repo_atlas.propose.heuristic import propose_heuristic as heuristic

    with pytest.raises(RepoAtlasError):
        run_git(tmp_path, ["status"])
    assert dirty_entries(tmp_path) == []
    ensure_clean(tmp_path, force=False)
    write(
        tmp_path / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    for index in range(13):
        write(tmp_path / f"tracked_{index}.txt", "ok\n")
    git_commit(tmp_path)
    for index in range(13):
        path = tmp_path / f"tracked_{index}.txt"
        path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(RepoAtlasError) as caught:
        ensure_clean(tmp_path, force=False)
    assert "and 1 more" in str(caught.value)

    manifest_dir = tmp_path / "undo-dir"
    manifest_dir.mkdir()
    with pytest.raises(RepoAtlasError):
        load_manifest(manifest_dir)
    write(tmp_path / "bad-version.json", '{"version": 2, "renames": [], "content_backups": []}\n')
    with pytest.raises(RepoAtlasError):
        load_manifest(tmp_path / "bad-version.json")
    (tmp_path / ".git" / "repo-atlas" / "undo").mkdir(parents=True)
    with pytest.raises(RepoAtlasError):
        latest_manifest(tmp_path)
    with pytest.raises(RepoAtlasError):
        plan_from_json('{"version": 9}')
    with pytest.raises(RepoAtlasError):
        plan_from_json('{"version": 1, "items": ["nope"]}')

    def _fake_llm(index, config, *, backend, client=None):
        del client
        assert backend in {"local", "api"}
        assert config.min_confidence == 0.4
        if backend == "local":
            assert config.local_model == "local-demo"
            assert config.local_base_url == "http://127.0.0.1:9/v1"
        else:
            assert config.api_model == "api-demo"
        return heuristic(index, config)

    monkeypatch.setattr("repo_atlas.cli.propose_llm", _fake_llm)
    assert (
        main(
            [
                "propose",
                str(tmp_path),
                "--backend",
                "local",
                "--model",
                "local-demo",
                "--base-url",
                "http://127.0.0.1:9/v1",
                "--min-confidence",
                "0.4",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "propose",
                str(tmp_path),
                "--backend",
                "api",
                "--model",
                "api-demo",
                "--base-url",
                "https://example.invalid/v1",
                "--min-confidence",
                "0.4",
            ]
        )
        == 0
    )


def test_javascript_index_resolution(tmp_path: Path) -> None:
    write(tmp_path / "web" / "misc" / "index.ts", "export const value = 1;\n")
    write(tmp_path / "web" / "index.js", "")
    ctx = RewriteContext(
        root=tmp_path,
        file_map={
            Path("web/index.js"): Path("web/index.js"),
            Path("web/misc/index.ts"): Path("web/checkout/index.ts"),
        },
    )
    updated = JavaScriptRewriter().rewrite(
        'import value from "./misc";\nimport nope from "../../outside";\n',
        Path("web/index.js"),
        ctx,
    )
    assert 'from "./checkout"' in updated or 'from "./checkout/index"' in updated
    assert "../../outside" in updated


def test_ingest_file_and_undo_roundtrip(tmp_path: Path) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    git_commit(tmp_path)
    config = Config(root=tmp_path)
    index = scan_repo(tmp_path, config)
    draft, _prompt = build_agent_pack(index, config)
    draft.items[0].proposed_name = "verify_signature.py"
    draft.items[0].confidence = 0.66
    draft.items[0].reason = "Signatures."
    path = tmp_path / "agent.json"
    from repo_atlas.plan import save_plan

    save_plan(draft, path)
    plan = ingest_agent_file(path, index, config)
    report = apply_plan(
        tmp_path,
        plan,
        files=[item.path for item in index.files],
        write=True,
    )
    assert report.manifest_path
    manifest = load_manifest(Path(report.manifest_path))
    preview = undo_manifest(tmp_path, manifest, write=False)
    assert preview.dry_run
    assert preview.moves
    undo_manifest(tmp_path, manifest, write=True, use_git=False)
    assert (tmp_path / "utils.py").is_file()
