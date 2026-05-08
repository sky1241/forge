"""Cycle 4 E-1: subprocess tests for the installed `forge` entry point.

Existing tests call forge.main() with monkeypatched sys.argv. Those don't
catch failures specific to the installed CLI path:
  - missing setuptools console_scripts entry
  - broken `__main__` invocation
  - sys.path issues that monkeypatched calls bypass

These tests subprocess the actual `forge` shell command created by
`pip install -e .`. They skip cleanly if the entry point isn't present in
the test runner's venv (CI minimal jobs, source-only checkouts).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# The forge entry point lives next to the python interpreter in the venv
# (sys.executable's parent). We pin that path explicitly rather than rely
# on PATH lookup, so the test exercises the entry point this venv would
# actually invoke.
_FORGE_BIN = Path(sys.executable).parent / "forge"


def _has_forge_entry() -> bool:
    return _FORGE_BIN.exists() and os.access(_FORGE_BIN, os.X_OK)


pytestmark = pytest.mark.skipif(
    not _has_forge_entry(),
    reason=f"forge entry point not installed at {_FORGE_BIN} "
           f"(install via `pip install -e .` or skip)",
)


def _run_forge(
    *args: str, cwd: Path | None = None, timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Subprocess the installed `forge` entry point with the given args."""
    return subprocess.run(
        [str(_FORGE_BIN), *args],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def _make_minimal_repo(root: Path) -> None:
    """Init a git repo at root with one source file and one passing test
    so `forge --baseline` has something to time."""
    (root / "main.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    (root / "test_main.py").write_text(
        "from main import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "-m", "init"],
        cwd=root, check=True,
    )


class TestCliEntryPoint:
    """Pin that `forge` (the setuptools-installed console script) starts
    cleanly from a fresh subprocess across the 5 most-used CLI paths."""

    def test_help_shows_usage(self) -> None:
        """`forge --help` exits 0 and prints usage text."""
        result = _run_forge("--help")
        assert result.returncode == 0, (
            f"forge --help should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        out = result.stdout.lower()
        assert "forge" in out or "usage" in out, (
            f"--help output didn't mention forge or usage:\n{result.stdout}"
        )

    def test_init_creates_forge_dir_and_bugs_md(self, tmp_path: Path) -> None:
        """`forge --init` scaffolds .forge/ + BUGS.md in the repo root.

        forge.find_repo_root walks up looking for .git/, so we git-init
        tmp_path first; otherwise it'd fall back to the script's parent
        (this checkout) and init there."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        result = _run_forge("--init", cwd=tmp_path)
        assert result.returncode == 0, (
            f"forge --init should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert (tmp_path / ".forge").is_dir(), (
            f"forge --init didn't create .forge/ dir; stdout:\n{result.stdout}"
        )
        assert (tmp_path / "BUGS.md").exists(), (
            f"forge --init didn't create BUGS.md; stdout:\n{result.stdout}"
        )
        assert (tmp_path / ".forge" / ".gitignore").exists()

    def test_baseline_runs_on_minimal_repo(self, tmp_path: Path) -> None:
        """`forge --baseline` on a minimal repo (1 source, 1 passing test)
        completes 0 and writes a baseline JSON under .forge/."""
        _make_minimal_repo(tmp_path)
        result = _run_forge("--baseline", cwd=tmp_path, timeout=120)
        assert result.returncode == 0, (
            f"forge --baseline should exit 0 on minimal repo;\n"
            f"got {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        forge_dir = tmp_path / ".forge"
        assert forge_dir.exists(), "expected .forge/ dir after --baseline"
        baselines = list(forge_dir.glob("*.json"))
        assert baselines, (
            f"expected at least one .json file in .forge/ after --baseline;\n"
            f"contents: {list(forge_dir.iterdir())}"
        )

    def test_predict_with_weeks_doesnt_traceback(self, tmp_path: Path) -> None:
        """`forge --predict --weeks 4` doesn't blow up with a Python
        traceback on a minimal repo. Whatever the exit code (0 with a
        "no data" message vs non-zero), the contract for a CLI is that
        a missing-data condition surfaces cleanly, not as a stack trace."""
        _make_minimal_repo(tmp_path)
        result = _run_forge("--predict", "--weeks", "4", cwd=tmp_path, timeout=60)
        assert "Traceback" not in result.stderr, (
            f"forge --predict --weeks 4 raised an unhandled exception:\n"
            f"{result.stderr}"
        )

    def test_unknown_flag_rejected_by_validator(self) -> None:
        """`forge --frobulate` (unknown flag) is rejected by `_validate_args`
        with exit 2 and the unknown flag name surfaced (cycle 4 P-something
        added the difflib `did you mean` hint)."""
        result = _run_forge("--frobulate", timeout=10)
        assert result.returncode == 2, (
            f"forge --frobulate should exit 2 (unknown flag);\n"
            f"got {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "frobulate" in combined or "unknown" in combined, (
            f"validator didn't surface unknown flag name:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
