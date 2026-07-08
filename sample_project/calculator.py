"""
Calculator module with intentional bugs for DuraAgent demo.

Each function has a docstring explaining the INTENDED behavior.
The bugs are realistic — the kind an agent would find in a code review.
"""


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


def divide(a: float, b: float) -> float:
    """
    Return a divided by b.

    Should raise ValueError if b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def average(numbers: list[float]) -> float:
    """
    Return the arithmetic mean of a list of numbers.

    Should raise ValueError if the list is empty.
    """
    if not numbers:
        raise ValueError("Cannot compute average of empty list")
    total = sum(numbers)
    return total / len(numbers)


def power(base: float, exp: float) -> float:
    """
    Return base raised to the power of exp.

    power(2, 3) should return 8.
    """
    return base ** exp


def percentage(value: float, total: float) -> float:
    """
    Return what percentage `value` is of `total`.

    percentage(25, 200) should return 12.5
    Should raise ValueError if total is zero.
    """
    if total == 0:
        raise ValueError("Total cannot be zero")
    # BUG: Floating point issue — doesn't round, produces artifacts like 33.33333333333333
    return value / total * 100
