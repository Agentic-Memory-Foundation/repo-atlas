import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(BENCH))

from metrics import (  # noqa: E402
    hit_at,
    map_locates,
    parse_features,
    primary_needle,
    rank_paths,
    simulate_agent,
)


def test_stemmer_and_rank() -> None:
    assert primary_needle("signatures") == "signature"
    assert primary_needle("verifies") == "verify"
    assert primary_needle("formatted") == "format"
    assert primary_needle("applied") == "apply"
    assert primary_needle("calculated") == "calculat"
    paths = [
        "shop/utils.py",
        "shop/verify_stripe_webhook_signature.py",
        "shop/create_stripe_refund.py",
    ]
    ranked = rank_paths("where is the code that verifies webhook signatures?", paths)
    assert hit_at(ranked, "shop/verify_stripe_webhook_signature.py", 1)
    assert not hit_at(ranked, "shop/utils.py", 1)
    refund = rank_paths("where are stripe refunds created?", paths)
    assert hit_at(refund, "shop/create_stripe_refund.py", 1)


def test_simulated_agent_and_map() -> None:
    before = ["shop/utils.py", "shop/helpers.py"]
    after = ["shop/verify_stripe_webhook_signature.py", "shop/calculate_invoice_tax.py"]
    question = "where is the code that verifies webhook signatures?"
    text = "Verify Stripe webhook signatures using the endpoint secret."
    early = simulate_agent(question, before, "shop/utils.py", text)
    late = simulate_agent(question, after, "shop/verify_stripe_webhook_signature.py", text)
    assert early["found_by"] == "grep"
    assert late["found_by"] == "glob"
    assert int(late["calls"]) < int(early["calls"])
    features = parse_features(
        "<!-- repo-atlas:start -->\n"
        "- `shop/`: Verify Stripe webhook signatures.\n"
        "- `shop/verify_stripe_webhook_signature.py`: Verify Stripe webhook signatures.\n"
        "<!-- repo-atlas:end -->\n"
    )
    assert len(features) == 1
    assert map_locates(question, features, "shop/verify_stripe_webhook_signature.py")
