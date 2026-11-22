from repo_atlas.naming import (
    build_filename,
    humanize,
    is_generic_stem,
    naming_style_for,
    valid_stem,
)


def test_generic_stems() -> None:
    for name in ("utils", "helpers", "misc", "stuff2", "file2", "tmp", "my_utils", "a"):
        assert is_generic_stem(name), name
    assert not is_generic_stem("create_stripe_refund")
    assert not is_generic_stem("verify_stripe_webhook_signature")


def test_python_names_are_always_snake() -> None:
    assert naming_style_for("python", "kebab") == "snake"
    assert naming_style_for("javascript", "auto") == "kebab"
    filename = build_filename(
        ["calculate", "cart", "total"],
        ".py",
        "python",
        "kebab",
    )
    assert filename == "calculate_cart_total.py"


def test_keyword_and_javascript_style() -> None:
    assert build_filename(["class"], ".py", "python", "auto") == "class_mod.py"
    assert build_filename(["calculate", "cart", "total"], ".js", "javascript", "auto") == (
        "calculate-cart-total.js"
    )
    assert not valid_stem("123abc", "python")
    assert humanize("verify_stripe_webhook") == "Verify stripe webhook"
