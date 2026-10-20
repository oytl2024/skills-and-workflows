"""Shared conservative request sizing independent of research stage counts."""


CONSERVATIVE_BATCH_CEILING = 5
MIN_POLL_SECONDS = 1.0
MAX_POLL_SECONDS = 60.0


def choose_batch_size(policy: dict, remaining_candidates: int, remaining_budget: int,
                      remaining_quota: int | None) -> int:
    """Input: policy dict and remaining counts ints. Output: int. Bound each HTTP batch without claiming platform capability."""
    requested = int(policy.get("requested_size", CONSERVATIVE_BATCH_CEILING))
    if requested <= 0:
        raise ValueError("requested_size must be positive")
    limits = [requested, CONSERVATIVE_BATCH_CEILING, max(0, int(remaining_candidates)),
              max(0, int(remaining_budget))]
    if remaining_quota is not None:
        limits.append(max(0, int(remaining_quota)))
    return min(limits)


def next_poll_delay(policy: dict, attempt: int, retry_after: float | None, jitter: float) -> float:
    """Input: policy dict, attempt int, optional server seconds and jitter float. Output: float. Pace bounded polling."""
    minimum = max(MIN_POLL_SECONDS, float(policy.get("min_poll_seconds", MIN_POLL_SECONDS)))
    maximum = max(minimum, float(policy.get("max_poll_seconds", MAX_POLL_SECONDS)))
    if retry_after is not None:
        return max(minimum, float(retry_after))
    backoff = minimum * (2 ** min(10, max(0, int(attempt))))
    return min(maximum, backoff + max(0.0, min(1.0, float(jitter))))
