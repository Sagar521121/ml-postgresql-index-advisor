import math
from typing import Optional


DEFAULT_MIN_TIMEOUT_SECONDS = 30.0
DEFAULT_TIMEOUT_MULTIPLIER = 1.5
DEFAULT_EPSILON_MS = 1.0


def calculate_dynamic_timeout_limit(
    t_baseline_ms: Optional[float],
    min_timeout_seconds: float = DEFAULT_MIN_TIMEOUT_SECONDS,
    multiplier: float = DEFAULT_TIMEOUT_MULTIPLIER,
) -> float:
    """
    Calculate dynamic timeout limit:
    T_limit = max(30 seconds, 1.5 * T_baseline)

    Returns T_limit in milliseconds.
    """
    min_timeout_ms = min_timeout_seconds * 1000.0  # 30,000 ms

    if t_baseline_ms is None or t_baseline_ms <= 0:
        return min_timeout_ms

    return max(min_timeout_ms, multiplier * float(t_baseline_ms))


def compute_speedup_target(
    t_baseline_ms: Optional[float],
    t_effective_ms: Optional[float],
    epsilon_ms: float = DEFAULT_EPSILON_MS,
) -> Optional[float]:
    """
    Compute log speedup ratio:
    target = log((T_baseline + epsilon) / (T_effective + epsilon))
    where epsilon = 1.0 ms.
    """
    if t_baseline_ms is None or t_effective_ms is None:
        return None

    numerator = float(t_baseline_ms) + epsilon_ms
    denominator = float(t_effective_ms) + epsilon_ms

    if numerator <= 0 or denominator <= 0:
        return None

    return math.log(numerator / denominator)


def compute_timeout_target(
    t_baseline_ms: Optional[float],
    t_limit_ms: Optional[float],
    epsilon_ms: float = DEFAULT_EPSILON_MS,
) -> Optional[float]:
    """
    Compute the conservative bound-derived timeout target:
    y_timeout = log((T_baseline + epsilon) / (T_limit + epsilon))
    where epsilon = 1.0 ms.

    IMPORTANT: This is a conservative bound-derived training target,
    NOT the actual runtime.
    """
    return compute_speedup_target(
        t_baseline_ms=t_baseline_ms,
        t_effective_ms=t_limit_ms,
        epsilon_ms=epsilon_ms,
    )
