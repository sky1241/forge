"""Tiny calculator used by examples/calculator — pin one regression scenario."""


def add(a: int, b: int) -> int:
    return a + b


def mul(a: int, b: int) -> int:
    return a * b


def divide(a: int, b: int) -> float:
    if b == 0:
        raise ZeroDivisionError("can't divide by zero")
    return a / b
