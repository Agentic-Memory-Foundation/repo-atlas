"""Project entry point. The file name is conventional and must stay put."""

from shop.utils import verify_stripe_webhook_signature


def main() -> None:
    ok = verify_stripe_webhook_signature(b"{}", "t=1,v1=abc", "secret")
    print(ok)


if __name__ == "__main__":
    main()
