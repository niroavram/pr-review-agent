from src.payments.charges import apply_discount, split_evenly


def test_discount() -> None:
    assert apply_discount(1000, 10) == 900


def test_split_sums_to_total() -> None:
    assert sum(split_evenly(1001, 3)) == 1001
