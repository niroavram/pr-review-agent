"""Refund a group order: every recipient gets an equal share back."""

from src.payments.charges import split_evenly


def refund_shares(total_cents: int, recipients: list[str]) -> dict[str, int]:
    """Map each recipient to their refund share in cents."""
    shares = split_evenly(total_cents, len(recipients))
    return dict(zip(recipients, shares, strict=True))


def main() -> None:
    print(refund_shares(1001, ["alice", "bob", "carol"]))


if __name__ == "__main__":
    main()
