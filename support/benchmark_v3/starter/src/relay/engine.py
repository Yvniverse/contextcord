from collections.abc import Callable

from .client import next_checkpoint, parse_retry_after
from .policy import RetryPolicy
from .report import AttemptRecord, ContinuationReport

Response = dict[str, object]


def continue_upload(
    send: Callable[[str | None], Response],
    sleep: Callable[[float], None],
    checkpoint: str | None = None,
    policy: RetryPolicy | None = None,
) -> ContinuationReport:
    policy = policy or RetryPolicy()
    report = ContinuationReport(checkpoint=checkpoint)
    current_checkpoint = checkpoint

    for attempt in range(1, policy.max_attempts + 1):
        response = send(current_checkpoint)
        status = int(response["status"])
        headers = dict(response.get("headers", {}))
        returned_checkpoint = next_checkpoint(headers.get("X-Relay-Checkpoint"))
        if returned_checkpoint is not None:
            current_checkpoint = returned_checkpoint

        report.attempts.append(
            AttemptRecord(
                number=attempt,
                status=status,
                checkpoint=current_checkpoint,
                scheduled_delay=0.0,
            )
        )
        report.final_status = status
        report.checkpoint = current_checkpoint

        if 200 <= status < 300:
            report.success = True
            return report
        if status not in policy.retry_statuses:
            return report

        delay = parse_retry_after(headers.get("Retry-After"))
        if delay is None:
            delay = min(0.1 * (2 ** (attempt - 1)), policy.max_single_delay)
        else:
            delay = min(delay, policy.max_single_delay)

        if report.total_scheduled_delay + delay > policy.total_delay_budget:
            return report

        report.total_scheduled_delay += delay
        report.attempts[-1] = AttemptRecord(
            number=attempt,
            status=status,
            checkpoint=current_checkpoint,
            scheduled_delay=delay,
        )
        sleep(delay)

    return report
