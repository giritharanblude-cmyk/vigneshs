"""Mathematical helpers for trend calculations."""
from typing import Optional


def calculate_yoy(current_value: float, previous_value: float) -> Optional[float]:
    """Year-over-year growth percentage."""
    if previous_value is None or previous_value == 0:
        return None
    return ((current_value - previous_value) / abs(previous_value)) * 100


def calculate_mom(current_value: float, previous_value: float) -> Optional[float]:
    """Month-over-month growth percentage."""
    if previous_value is None or previous_value == 0:
        return None
    return ((current_value - previous_value) / abs(previous_value)) * 100


def calculate_rolling_change(latest_12m: float, prev_12m: float) -> Optional[float]:
    """Rolling 12-month change percentage."""
    if prev_12m is None or prev_12m == 0:
        return None
    return ((latest_12m - prev_12m) / abs(prev_12m)) * 100


def clamp01(value: float) -> float:
    """Clamp a value to the [0, 1] range."""
    if value is None:
        return 0.0
    return min(max(value, 0.0), 1.0)
