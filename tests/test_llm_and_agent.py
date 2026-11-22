import json
from pathlib import Path

import httpx

from conftest import write
from repo_atlas.config import Config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.plan import plan_to_json
from repo_atlas.propose.agent import build_agent_pack, ingest_agent_plan
from repo_atlas.propose.llm import propose_llm
from repo_atlas.scan import scan_repo


def _repo(tmp_path: Path) -> Path:
    write(
        tmp_path / "utils.py",
        '"""Verify Stripe webhook signatures."""\n\ndef verify_stripe_webhook_signature():\n    return True\n',
    )
    return tmp_path


def test_local_backend_uses_model_names(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers.get("authorization") == "Bearer local-key"
        body = json.dumps(
            {
                "renames": [
                    {
                        "path": "utils.py",
                        "kind": "file",
                        "proposed_name": "verify_stripe_webhook_signature.py",
                        "reason": "The module verifies signatures.",
                        "confidence": 0.88,
                    }
                ]
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    monkeypatch.setenv("REPO_ATLAS_LOCAL_API_KEY", "local-key")
    config = Config(root=root, backend="local", local_model="demo")
    index = scan_repo(root, config)
    plan = propose_llm(
        index,
        config,
        backend="local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert plan.backend == "local"
    assert plan.items[0].proposed_name == "verify_stripe_webhook_signature.py"
    assert plan.items[0].reason == "The module verifies signatures."


def test_api_backend_requires_a_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("REPO_ATLAS_API_KEY", raising=False)
    root = _repo(tmp_path)
    config = Config(root=root)
    index = scan_repo(root, config)
    try:
        propose_llm(index, config, backend="api")
    except RepoAtlasError as exc:
        assert "REPO_ATLAS_API_KEY" in str(exc)
    else:
        raise AssertionError("expected a missing key error")


def test_invalid_model_json_falls_back_to_heuristics(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    config = Config(root=root)
    index = scan_repo(root, config)
    plan = propose_llm(
        index,
        config,
        backend="local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert plan.items[0].proposed_name == "verify_stripe_webhook_signature.py"
    assert plan.warnings


def test_agent_export_and_ingest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    config = Config(root=root)
    index = scan_repo(root, config)
    draft, prompt = build_agent_pack(index, config)
    assert "proposed_name" in prompt
    assert draft.items[0].proposed_name == ""
    draft.items[0].proposed_name = "verify_stripe_webhook_signature.py"
    draft.items[0].reason = "Filled by the agent."
    draft.items[0].confidence = 0.93
    plan = ingest_agent_plan(draft, index, config)
    assert plan.backend == "agent"
    assert plan.items[0].proposed_path == "verify_stripe_webhook_signature.py"
    text = plan_to_json(plan)
    assert "verify_stripe_webhook_signature.py" in text


def test_agent_ingest_rejects_a_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    config = Config(root=root)
    index = scan_repo(root, config)
    draft, _prompt = build_agent_pack(index, config)
    draft.items[0].proposed_name = "../escape.py"
    draft.items[0].confidence = 0.9
    try:
        ingest_agent_plan(draft, index, config)
    except RepoAtlasError as exc:
        assert "single name" in str(exc)
    else:
        raise AssertionError("expected a path rejection")
