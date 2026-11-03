from src.utils.pagination import paginate


def test_first_page() -> None:
    assert paginate(["a", "b", "c", "d"], 1, 2) == ["a", "b"]


def test_last_page() -> None:
    assert paginate(["a", "b", "c", "d"], 2, 2) == ["c", "d"]
