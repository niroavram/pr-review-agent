def page_bounds(page: int, per_page: int) -> tuple[int, int]:
    """Return (start, end) slice indices for a 1-based page number."""
    start = (page - 1) * per_page
    return start, start + per_page


def paginate(items: list[str], page: int, per_page: int) -> list[str]:
    start, end = page_bounds(page, per_page)
    return items[start:end]
