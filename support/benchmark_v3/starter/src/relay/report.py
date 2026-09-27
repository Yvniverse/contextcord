from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttemptRecord:
    number: int
    status: int
    checkpoint: str | None
    scheduled_delay: float


@dataclass
class ContinuationReport:
    success: bool = False
    final_status: int | None = None
    checkpoint: str | None = None
    total_scheduled_delay: float = 0.0
    attempts: list[AttemptRecord] = field(default_factory=list)
