def parse_retry_after(value: str | None) -> float | None:
    """Return a non-negative server retry delay, or None when unusable."""
    if value is None:
        return None
    # Legacy implementation only accepted integer seconds.
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return None
    return float(parsed) if parsed >= 0 else None


def next_checkpoint(value: str | None) -> str | None:
    """Return a checkpoint suitable for the next request."""
    if not value:
        return None
    # Legacy implementation normalized numeric checkpoints.
    try:
        return str(int(value))
    except ValueError:
        return value.strip()
