from pathlib import Path

from conftest import git_commit, write
from repo_atlas.apply import apply_plan
from repo_atlas.config import Config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.plan import PlanItem, RenamePlan
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.rewrite import base as rewrite_base
from repo_atlas.scan import scan_repo
from repo_atlas.undo import latest_manifest, undo_manifest


def _python_repo(root: Path) -> None:
    write(root / "pkg" / "__init__.py", "from .utils import verify_signature\n")
    write(
        root / "pkg" / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature() -> bool:\n    return True\n',
    )
    write(root / "pkg" / "other.py", "from .utils import verify_signature\n\nverify_signature()\n")


def test_dry_run_does_not_touch_files(git_repo: Path) -> None:
    _python_repo(git_repo)
    git_commit(git_repo)
    config = Config(root=git_repo)
    index = scan_repo(git_repo, config)
    plan = propose_heuristic(index, config)
    report = apply_plan(git_repo, plan, files=[item.path for item in index.files], write=False)
    assert report.dry_run
    assert any(src == "pkg/utils.py" for src, _dest in report.moves)
    assert (git_repo / "pkg" / "utils.py").is_file()
    assert "verify_signature" in (git_repo / "pkg" / "__init__.py").read_text(encoding="utf-8")


def test_apply_rewrites_imports_and_undo_restores(git_repo: Path) -> None:
    _python_repo(git_repo)
    git_commit(git_repo)
    config = Config(root=git_repo)
    index = scan_repo(git_repo, config)
    plan = propose_heuristic(index, config)
    report = apply_plan(
        git_repo,
        plan,
        files=[item.path for item in index.files],
        write=True,
    )
    assert report.manifest_path
    assert not (git_repo / "pkg" / "utils.py").exists()
    renamed = git_repo / "pkg" / "verify_signature.py"
    assert renamed.is_file()
    init = (git_repo / "pkg" / "__init__.py").read_text(encoding="utf-8")
    assert "from .verify_signature import verify_signature" in init
    other = (git_repo / "pkg" / "other.py").read_text(encoding="utf-8")
    assert "from .verify_signature import verify_signature" in other
    manifest = latest_manifest(git_repo)
    undo_manifest(git_repo, manifest, write=True)
    assert (git_repo / "pkg" / "utils.py").is_file()
    restored = (git_repo / "pkg" / "__init__.py").read_text(encoding="utf-8")
    assert restored == "from .utils import verify_signature\n"


def test_dirty_tree_is_refused_until_forced(git_repo: Path) -> None:
    _python_repo(git_repo)
    git_commit(git_repo)
    utils = git_repo / "pkg" / "utils.py"
    utils.write_text(utils.read_text(encoding="utf-8") + "\n# dirty\n", encoding="utf-8")
    config = Config(root=git_repo)
    index = scan_repo(git_repo, config)
    plan = propose_heuristic(index, config)
    try:
        apply_plan(git_repo, plan, files=[item.path for item in index.files], write=True)
    except RepoAtlasError as exc:
        assert "dirty" in str(exc)
    else:
        raise AssertionError("expected a dirty tree error")
    report = apply_plan(
        git_repo,
        plan,
        files=[item.path for item in index.files],
        write=True,
        force=True,
    )
    assert report.manifest_path
    assert (git_repo / "pkg" / "verify_signature.py").is_file()


def test_swap_and_plugin_rewriter(git_repo: Path) -> None:
    write(git_repo / "a.py", "print('a')\n")
    write(git_repo / "b.py", "print('b')\n")
    write(git_repo / "notes.txt", "see a.py and b.py\n")
    git_commit(git_repo)

    class NotesRewriter:
        def handles(self, path: Path) -> bool:
            return path.suffix == ".txt"

        def rewrite(self, source: str, path: Path, ctx) -> str:
            del path
            moves = [(old.name, new.name) for old, new in ctx.file_map.items() if old != new]
            for index, (old, _new) in enumerate(moves):
                source = source.replace(old, f"__MOVE_{index}__")
            for index, (_old, new) in enumerate(moves):
                source = source.replace(f"__MOVE_{index}__", new)
            return source

    rewriter = NotesRewriter()
    rewrite_base.register_rewriter(rewriter)
    try:
        plan = RenamePlan(
            version=1,
            backend="none",
            root=str(git_repo),
            items=[
                PlanItem(
                    path="a.py",
                    kind="file",
                    language="python",
                    current_name="a.py",
                    proposed_name="b.py",
                    proposed_path="b.py",
                    reason="swap",
                    confidence=0.9,
                ),
                PlanItem(
                    path="b.py",
                    kind="file",
                    language="python",
                    current_name="b.py",
                    proposed_name="a.py",
                    proposed_path="a.py",
                    reason="swap",
                    confidence=0.9,
                ),
            ],
            path_map=[{"from": "a.py", "to": "b.py"}, {"from": "b.py", "to": "a.py"}],
        )
        apply_plan(
            git_repo,
            plan,
            files=[Path("a.py"), Path("b.py"), Path("notes.txt")],
            write=True,
        )
    finally:
        rewrite_base._REGISTRY.remove(rewriter)
    assert (git_repo / "a.py").read_text(encoding="utf-8") == "print('b')\n"
    assert (git_repo / "b.py").read_text(encoding="utf-8") == "print('a')\n"
    assert (git_repo / "notes.txt").read_text(encoding="utf-8") == "see b.py and a.py\n"


def test_no_git_rename(tmp_path: Path) -> None:
    write(
        tmp_path / "utils.py",
        '"""Verify webhook signatures."""\n\ndef verify_signature():\n    return True\n',
    )
    config = Config(root=tmp_path)
    index = scan_repo(tmp_path, config)
    plan = propose_heuristic(index, config)
    apply_plan(
        tmp_path,
        plan,
        files=[item.path for item in index.files],
        write=True,
        use_git=False,
    )
    assert (tmp_path / "verify_signature.py").is_file()
