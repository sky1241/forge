"""Tests for examples/calculator. Note: deliberately no test for mul()
so `forge --mutate` surfaces the test-gap on a real example."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from calculator import add, divide  # noqa: E402

import pytest


def test_add():
    assert add(1, 2) == 3


def test_add_negative():
    assert add(-5, 3) == -2


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero_raises():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
