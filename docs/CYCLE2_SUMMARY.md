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

### ✅ FIXED — `find_tests()` honors `[tool.pytest.ini_options] norecursedirs`
**Found by cousin pc1 on pytest.** Now reads `pyproject.toml` via stdlib
`tomllib` (Python 3.11+) and excludes any dir listed in
`norecursedirs`. Test: `TestFindTestsHonorsNoRecursedirs`.

### ✅ FIXED — `--gen-props` sys.path no longer pollutes external imports
**Found by cousin pc1 on mkdocs.** Removed the inner-module-dir insertion
that shadowed PyPI packages (e.g. `<repo>/mkdocs/utils/yaml.py` vs
`yaml` package). Only the repo root is now inserted. Test:
`TestGenPropsNoSysPathPollution`.

### ✅ FIXED — `--gen-props` exception whitelist broadened + None-safety
**Found by cousin pc1.** The smoke-test except clause now catches
`SyntaxError`, `LookupError`, `ArithmeticError`, `AssertionError` and
`Exception` (catch-all for custom package exceptions like
`pytest.UsageError`). The "subset" test now guards `if result is not
None:` before `len(result)`. Tests:
`TestGenPropsExceptionWhitelistBroader`, `TestGenPropsSubsetTestNoneSafe`.

### ✅ FIXED — `--predict` clamps `loc` to `MIN_PREDICT_LOC` for churn ratio
**First reported on scrapy** (earlier session), **confirmed on pytest**
this cycle. `churn_rel = (added+deleted) / max(loc, 10)` so trivial
1-line stubs can't dominate ranking. Test: `TestPredictMinLocClamp`.

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

## Cycle 2.5 — cousin pc1 dug 4 deeper findings, all fixed

After Sky asked "but does the code do what it promises?" the cousin
audited forge against its own claims and surfaced 7 more issues. The 4
real bugs are now fixed:

### ✅ FIXED — `forge` default compares per-test SETS, not just counts

**The structural lie**: if `test_a` flipped passed→failed AND `test_b`
flipped failed→passed, the count delta was 0 → `forge` said "PASS"
silently while a real regression hid behind a compensating fix.

`run_tests` now stores `passed_tests / failed_tests / xfailed_tests /
xpassed_tests` as sorted lists in `baseline.json`. `print_report`
computes `baseline.passed ∩ now.failed` for *flipped* tests and lists
them by name. Legacy baselines (counts only) fall back to count-delta
behavior. Tests: `TestRunTestsTracksPerTestNames` (5).

### ✅ FIXED — XPASS surfaced as potential semantic regression

A test marked `@pytest.mark.xfail` that now PASSES means the bug it
documented may be fixed (or the marker is wrong). `print_report` now
diffs `now.xpassed - baseline.xpassed` and prints a ⚠️ block listing
the unexpectedly-passing xfails. Test:
`test_print_report_xpass_unexpected`.

### ✅ FIXED — `--gen-props` warns about its blind spot at the end

The destructive AST detector can't follow indirect calls
(`parse_input() → IndexBuilder() → mkdir()`). The autouse cwd guard in
the generated test file mitigates most cases, but module-level path
constants can still escape. `gen_props` now prints an explicit warning
after generation telling the user to run in a disposable clone or
`git stash` first. Test: indirectly via the existing
`TestGenPropsImportPathStripsInit` (the warning text is present).

### ✅ FIXED — `find_tests()` honors `[tool.pytest.ini_options] testpaths`

When pytest's testpaths is set (e.g. pytest's own repo:
`testpaths = ['testing']`), `find_tests` now scopes its globs to those
dirs. Before this, forge picked tests from the entire repo, including
dirs the user explicitly excluded from pytest's collection. Test:
`TestFindTestsHonorsTestPaths`.

## Findings documented as out-of-scope (not bugs)

- **#2 baseline doesn't track pytest config (`-n auto`, etc.)** — forge
  never invokes xdist/parallel; if the user changes their own pytest
  invocation between runs, that's user-side. Doc concern only.
- **#4 gen-props heuristic patterns may produce other false positives**
  — true but dependent on the package being mutated; we'd need to test
  on 5-10 modules to spot more. Out-of-scope this cycle. The `len(None)`
  case was the real one and is fixed.
- **#7 shallow clone bias on `--predict`** — the warning "small repo"
  already fires; user-side clone discipline is the right answer. The
  warning text is the doc.

## Total: 12 forge fixes + 16 new regression tests + 0 dette technique

97 tests pass on sky-master. Cycle 2 + 2.5 closed every actionable
finding from cousin pc1.
