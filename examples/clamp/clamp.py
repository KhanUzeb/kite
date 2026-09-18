"""Intentionally incorrect clamp — Kite / MiniMax-style coding exercise."""


def clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return low
    return value
