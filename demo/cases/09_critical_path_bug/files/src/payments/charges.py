def apply_discount(total_cents: int, percent: int) -> int:
    """Discounted total in cents. percent is 0-100."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be 0-100")
    return total_cents - (total_cents * percent) // 100


def split_evenly(total_cents: int, parts: int) -> list[int]:
    """Split an amount into `parts` shares that sum exactly to total_cents."""
    base, rem = divmod(total_cents, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def split_by_weights(total_cents: int, weights: list[int]) -> list[int]:
    """Split an amount proportionally to `weights`; shares sum exactly to total_cents."""
    total_weight = sum(weights)
    return [total_cents * w // total_weight for w in weights]
