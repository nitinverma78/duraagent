"""Tests for calculator module — 8 pass, 4 fail (exposing the 4 bugs)."""

import pytest
from calculator import add, subtract, multiply, divide, average, power, percentage


# ── PASSING TESTS (happy path) ────────────────────────────────────────

class TestBasicOperations:
    """These tests pass — they cover correct functionality."""

    def test_add(self):
        assert add(2, 3) == 5

    def test_add_negative(self):
        assert add(-1, 1) == 0

    def test_subtract(self):
        assert subtract(10, 3) == 7

    def test_multiply(self):
        assert multiply(4, 5) == 20

    def test_multiply_by_zero(self):
        assert multiply(100, 0) == 0

    def test_divide_normal(self):
        assert divide(10, 2) == 5.0

    def test_percentage_normal(self):
        assert percentage(25, 200) == 12.5

    def test_percentage_zero_total(self):
        with pytest.raises(ValueError, match="Total cannot be zero"):
            percentage(10, 0)


# ── FAILING TESTS (exposing bugs) ────────────────────────────────────

class TestBugs:
    """These tests FAIL — each one exposes a specific bug."""

    def test_divide_by_zero_should_raise(self):
        """BUG: divide(1, 0) should raise ValueError, but raises ZeroDivisionError."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(1, 0)

    def test_average_correctness(self):
        """BUG: average([1, 2, 3]) should return 2.0, but returns 3.0 (off-by-one)."""
        assert average([1, 2, 3]) == 2.0

    @pytest.mark.parametrize("base,exp,expected", [
        (2, 3, 8),
        (5, 2, 25),
        (10, 0, 1),
    ])
    def test_power(self, base, exp, expected):
        """BUG: power() uses * instead of ** — power(2,3) returns 6 instead of 8."""
        assert power(base, exp) == expected

    def test_percentage_precision(self):
        """BUG: percentage(1, 3) should return 33.33, but returns 33.33333..."""
        result = percentage(1, 3)
        assert result == round(result, 2), f"Expected rounded result, got {result}"
