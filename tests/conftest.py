"""Test fixtures shared across the suite.

Prepends the repo root to sys.path so `import forge` finds the canonical
forge.py at the repo root regardless of where pytest is invoked from. This
replaces the per-file `importlib.util.spec_from_file_location("forge_root",
...)` dance the suite used to do — that loaded the module under the alias
`forge_root`, which made `pytest --cov=forge` report 0% because coverage's
module discovery looks for the import name `forge`, not the alias.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
