# Cycle 2 — Auto-amélioration cross-tested

Date: 2026-05-08 night session
Forge HEAD before cycle: `5fc55c1`
Forge HEAD after cycle: `<current>` (pushed)

## Setup

Two Claude instances (sky-master + cousin pc1, talking via canal v0.5).
Each researched 3 open-bug GitHub repos for the OTHER to test. 6 real bug
reproductions on 6 different Python projects. Goal: auto-improve forge by
surfacing real-world failures.

## Cas testés

### Côté sky-master (researched by cousin pc1)

| # | Repo | Issue | Bug reproduced? |
|---|---|---|---|
| 1 | `lepture/mistune` | #433 nested `<pre>` in `<div>` | ✅ yes (1 fail captured) |
| 2 | `marshmallow-code/marshmallow` | #2961 Nested `@post_load` | ✅ yes (1 fail captured) |
| 3 | `agronholm/anyio` | #1132 AF_UNIX listener | ⚠️ partial (install lourd cascade) |

### Côté cousin pc1 (researched by sky-master)

| # | Repo | Issue | Bug reproduced? |
|---|---|---|---|
| 4 | `psf/black` | #5125 f-string dict-key single-quote | ❌ NOT REPRODUCIBLE on Python 3.13 (PEP 701 fixed it) |
| 5 | `pytest-dev/pytest` | #14442 strict-markers via addopts | ✅ yes (1 fail captured) |
| 6 | `mkdocs/mkdocs` | #4098 pygments 2.20 crash | ❌ generic repro insufficient (needs pymdownx.highlight) |

## Forge bugs surfaced (8 total, 4 fixed this cycle)

### ✅ FIXED — `--locate` silent on collection error (commit `f8754c5`)
**Found by sky-master on marshmallow.** When pytest crashed at collection
with exit code 2 (e.g. `tests/mypy_test_cases/` not meant for plain pytest),
`fault_locate` saw 0 PASSED + 0 FAILED, said "No failing tests" silently,
masked a real bug. Same anti-mensonge-silencieux pattern as the run_tests
parser fix and mutate timeout fix earlier this evening.

### ✅ FIXED — `--locate` crash on subprocess timeout
**Found by cousin pc1 on pytest.** With ~3500 test files × `--cov-context=test`,
the run blew the 600s timeout. `subprocess.TimeoutExpired` bubbled up as a
Python traceback. Now caught and surfaced as a clean message with hints
(FORGE_TEST_FILTER, reduce test files).

### ✅ FIXED — `find_tests()` ignores `*_tests.py` suffix
**Found by cousin pc1 on mkdocs.** mkdocs uses `build_tests.py`,
`cli_tests.py`, `plugin_tests.py` etc. — pytest's `python_files` config
accepts both prefix and suffix conventions, forge only matched
`test_*.py`. **19 test files were invisible** on mkdocs. Pattern added.

### ✅ FIXED — `--gen-props` redundant `__init__` in import path
**Found by cousin pc1 on mkdocs.** `gen-props mkdocs/utils/__init__.py`
generated `from mkdocs.utils.__init__ import *` instead of clean
`from mkdocs.utils import *`. Redundant + DeprecationWarning in 3.13+.

### ❌ NOT FIXED YET — `find_tests()` doesn't honor `norecursedirs`
**Found by cousin pc1 on pytest.** `pyproject.toml` had `norecursedirs =
["testing/example_scripts", ...]` but forge globbed all `**/test_*.py` and
hit those directories. Pytest then errored "ManifestDirectory not match".
Workaround: rm those dirs. **Future fix**: parse pyproject.toml's
`tool.pytest.ini_options.norecursedirs` and exclude.

### ❌ NOT FIXED YET — `--gen-props` sys.path pollution
**Found by cousin pc1 on mkdocs.** Generated test inserts the module's
parent dir into sys.path, which can shadow installed packages
(e.g. `<repo>/mkdocs/utils/yaml.py` shadowed PyPI `yaml` package). Should
NOT insert the inner module dir, just the repo root.

### ❌ NOT FIXED YET — `--gen-props` exception whitelist too narrow
**Found by cousin pc1.** Generated tests fail on legitimate exceptions
not in the default catch list:
- `SyntaxError` for parser functions (black on `parse_ast`)
- `pytest.UsageError` for CLI helpers
- `len(None)` in subset tests when function returns `None`

Auto-detection of package's custom exceptions or wider default catch needed.

### ❌ NOT FIXED YET — `--predict` artifact `loc=1` fallback
**First reported on scrapy** (earlier session), **confirmed on pytest**
this cycle. Files with `loc=1` (typically empty `__init__.py` or stubs)
get artificially inflated churn ratio. Need a minimum-loc threshold
before computing churn.

## Limitations documented (not bugs)

### Ochiai SBFL fails on pipeline bugs
**On mistune #433**: `--locate` pointed `def_list.py` at score 0.71 instead
of `block_parser.py` (the real culprit). When the failing test triggers
the entire pipeline (parser → renderer → plugins), every module gets the
same Ochiai score because they're all touched by the failing test. The
top-N is uniformly suspect, not actionable.

This is a known SBFL limitation in the literature; not a forge bug. Could
be improved in the future with more sophisticated SBFL variants
(Tarantula, DStar) or with stack-trace-based localization, but out of
scope for now.

### Repo extras `[X]` are systematically incomplete
On 6 repos this cycle (+ 3 previous): `pip install -e ".[dev]"` or
`".[tests]"` always leaves deps missing — pytest, pytest-cov, hypothesis,
pytest-mock, pytest-timeout, simplejson, etc. Not a forge issue, an
ecosystem pattern (PEP 735 dependency-groups not handled by `pip install
-e`). Forge's PYTEST RUNNER ERROR surfacing is the right behavior — it
shows the user EXACTLY what's missing instead of pretending tests don't
exist.

## Tests added this cycle

- `TestFaultLocateSurfacesCollectionErrors` — pytest exits non-zero with
  no PASSED/FAILED entries
- `TestFaultLocateTimeoutGraceful` — `subprocess.TimeoutExpired` caught
  cleanly, no Python traceback to user
- `TestFindTestsAlsoMatchesUnderscoreTests` — `*_tests.py` and `*_test.py`
  patterns picked up
- `TestGenPropsImportPathStripsInit` — `__init__.py` modules use clean
  import path

## Total: 4 forge fixes + 4 new regression tests + 4 bugs documented for future

85 tests pass on sky-master. Forge ↗.
