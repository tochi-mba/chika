"""Tests for the fib module."""
import pytest

from fib import fib_iterative, fib_recursive, fib_sequence


# ---------------------------------------------------------------------------
# Known values (OEIS A000045)
# ---------------------------------------------------------------------------
KNOWN = [
    (0,  0),
    (1,  1),
    (2,  1),
    (3,  2),
    (4,  3),
    (5,  5),
    (6,  8),
    (7,  13),
    (8,  21),
    (9,  34),
    (10, 55),
    (20, 6765),
    (30, 832040),
]


@pytest.mark.parametrize("n, expected", KNOWN)
def test_fib_iterative_known(n, expected):
    assert fib_iterative(n) == expected


@pytest.mark.parametrize("n, expected", KNOWN)
def test_fib_recursive_known(n, expected):
    assert fib_recursive(n) == expected


def test_fib_iterative_and_recursive_agree():
    """Both implementations must return identical results for 0..50."""
    for i in range(51):
        assert fib_iterative(i) == fib_recursive(i), f"mismatch at n={i}"


# ---------------------------------------------------------------------------
# fib_sequence
# ---------------------------------------------------------------------------
def test_fib_sequence_empty():
    assert fib_sequence(0) == []


def test_fib_sequence_one():
    assert fib_sequence(1) == [0]


def test_fib_sequence_ten():
    assert fib_sequence(10) == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("func", [fib_iterative, fib_recursive])
def test_negative_raises_value_error(func):
    with pytest.raises(ValueError):
        func(-1)


@pytest.mark.parametrize("func", [fib_iterative, fib_recursive])
def test_non_int_raises_type_error(func):
    with pytest.raises(TypeError):
        func(3.5)  # type: ignore[arg-type]


def test_sequence_negative_raises():
    with pytest.raises(ValueError):
        fib_sequence(-1)
