"""Shared metrics calculation utilities."""


def calc_stats(values: list[float]) -> dict[str, float]:
    """Calculate statistics for a list of values.

    Provides comprehensive statistics including basic measures (count, mean, min, max),
    total sum, and percentiles (p50, p95, p99). This is the canonical implementation
    shared across all metrics collection in the system.

    Args:
        values: List of numeric values (supports both list and deque)

    Returns:
        Dictionary with the following keys:
            - count: Number of values
            - mean: Average value
            - min: Minimum value
            - max: Maximum value
            - total: Sum of all values
            - p50: 50th percentile (median)
            - p95: 95th percentile
            - p99: 99th percentile

    Examples:
        >>> calc_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        {'count': 5, 'mean': 3.0, 'min': 1.0, 'max': 5.0, 'total': 15.0, 'p50': 3.0, 'p95': 5.0, 'p99': 5.0}

        >>> calc_stats([])
        {'count': 0, 'mean': 0.0, 'min': 0.0, 'max': 0.0, 'total': 0.0, 'p50': 0.0, 'p95': 0.0, 'p99': 0.0}
    """
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "total": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }

    # Convert to list if deque (supports both)
    values_list = list(values) if not isinstance(values, list) else values

    # Calculate basic statistics
    count = len(values_list)
    total = sum(values_list)
    mean = total / count
    min_val = min(values_list)
    max_val = max(values_list)

    # Calculate percentiles
    sorted_vals = sorted(values_list)
    n = len(sorted_vals)

    # Percentile calculation using nearest-rank method
    p50 = sorted_vals[int(n * 0.50)] if n > 0 else 0.0
    p95 = sorted_vals[int(n * 0.95)] if n > 20 else sorted_vals[-1] if n > 0 else 0.0
    p99 = sorted_vals[int(n * 0.99)] if n > 100 else sorted_vals[-1] if n > 0 else 0.0

    return {
        "count": count,
        "mean": mean,
        "min": min_val,
        "max": max_val,
        "total": total,
        "p50": p50,
        "p95": p95,
        "p99": p99,
    }
