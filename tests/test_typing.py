"""Type-checking regression test.

Cycle 4 C-C: pin `mypy --strict forge.py` returncode 0 as a slow test.
The test is excluded from the default suite via `pyproject.toml`'s
`addopts = "-m 'not slow'"` because mypy adds ~5-10s to the run.

Invoke explicitly with:

    pytest -m slow tests/test_typing.py
    pytest -m slow                    # all slow tests in the suite

The test guards against future commits that drop a return type, lose
a narrowing, or otherwise reintroduce mypy strict errors. Cousin pc1
cycle 4 Phase C ended at 0 errors / 1 ignore (pytest_timeout missing
stub) — anything beyond that means the contract slipped.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.slow
def test_mypy_strict_on_forge() -> None:
    """`mypy --strict forge.py` must return code 0 (Success).

    Cross-version: tested on mypy 1.20.x (sky-master) and 2.0 (cousin pc1).
    Both versions accept the per-element isinstance narrowing in
    `_kaplan_meier`'s legacy-shape handler — see commit aba25c9 for the
    diagnosis.
    """
    # Skip cleanly if mypy isn't installed in this venv (e.g. CI minimal
    # job that only installs the runtime deps). The test is opt-in via
    # `pytest -m slow` anyway, so users running it should have dev deps.
    pytest.importorskip("mypy")

    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "forge.py"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"mypy --strict failed (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
