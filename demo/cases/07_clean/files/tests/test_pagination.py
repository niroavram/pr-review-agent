from src.utils.pagination import clamp_page, paginate


def test_first_page() -> None:
    assert paginate(["a", "b", "c", "d"], 1, 2) == ["a", "b"]


def test_last_page() -> None:
    assert paginate(["a", "b", "c", "d"], 2, 2) == ["c", "d"]


def test_clamp_page() -> None:
    assert clamp_page(0, 3) == 1
    assert clamp_page(2, 3) == 2
    assert clamp_page(9, 3) == 3
    assert clamp_page(4, 0) == 1
