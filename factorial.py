"""Factorial calculation module."""


def factorial(n: int) -> int:
    """
    Calculate the factorial of a non-negative integer n.

    Args:
        n: A non-negative integer

    Returns:
        The factorial of n (n!)

    Raises:
        ValueError: If n is negative
        TypeError: If n is not an integer
    """
    if not isinstance(n, int):
        raise TypeError(f"Expected int, got {type(n).__name__}")
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    if n == 0 or n == 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


if __name__ == "__main__":
    import sys
    try:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        print(f"{n}! = {factorial(n)}")
    except (ValueError, TypeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)