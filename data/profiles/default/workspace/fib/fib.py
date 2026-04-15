"""Fibonacci module — iterative and recursive implementations."""
from functools import lru_cache


def fib_iterative(n: int) -> int:
    """Return the n-th Fibonacci number (0-indexed) iteratively.

    fib(0) == 0, fib(1) == 1, fib(2) == 1, ...

    Args:
        n: Non-negative integer index.

    Raises:
        ValueError: If n is negative.
    """
    if not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


@lru_cache(maxsize=None)
def fib_recursive(n: int) -> int:
    """Return the n-th Fibonacci number (0-indexed) recursively with memoisation.

    Args:
        n: Non-negative integer index.

    Raises:
        TypeError:  If n is not an int.
        ValueError: If n is negative.
    """
    if not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if n < 2:
        return n
    return fib_recursive(n - 1) + fib_recursive(n - 2)


def fib_sequence(count: int) -> list[int]:
    """Return a list of the first *count* Fibonacci numbers.

    Args:
        count: How many numbers to generate (>= 0).

    Raises:
        ValueError: If count is negative.
    """
    if count < 0:
        raise ValueError(f"count must be >= 0, got {count}")
    return [fib_iterative(i) for i in range(count)]
