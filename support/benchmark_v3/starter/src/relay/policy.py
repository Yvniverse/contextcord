from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    total_delay_budget: float = 1.2
    max_single_delay: float = 0.75
    retry_statuses: tuple[int, ...] = (429, 503)
