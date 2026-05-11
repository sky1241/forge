# Changelog

All notable changes to forge are documented here. Format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet. See [GitHub issues](https://github.com/sky1241/forge/issues)._

## [1.3.0rc1] - 2026-05-11

**Release candidate.** Adds cold-start complexity signal to `forge --carmack`
to address the cold-start blind spot identified in cycle 12 v3 / cycle 13 v4
(carmack signals all 0 on files with 0 prior bugfixes).

### Added
- **6th signal `complexity` in carmack composite** — non-history-based AST
  metric combining:
  - McCabe 1976 cyclomatic complexity (decision points + 1 base)
  - Halstead 1977 software science (volume, difficulty, effort)
  - Max nesting depth (If / For / While / Try / With / FunctionDef)
  - LOC penalty
  All pure Python stdlib (no numpy/scipy). AST-based.
  Reference: Menzies-Greenwald-Frank 2007 "Data Mining Static Code
  Attributes to Learn Defect Predictors" IEEE TSE.

- **3 new top-level functions** in `forge.py`:
  - `_compute_mccabe_complexity(source: str) -> int`
  - `_compute_halstead_metrics(source: str) -> dict[str, float]`
  - `_compute_max_nesting_depth(source: str) -> int`
  - `_compute_complexity_score(file_path: Path) -> float` (combined, [0, 1])

- **16 new tests** in `TestCycle14ColdStartComplexity` class covering:
  - McCabe edge cases (simple if, zero decision, nested loops, bool chains, syntax error)
  - Halstead formulas (volume / difficulty match formula, empty source, syntax error)
  - Nesting depth (flat, function with if/for)
  - Complexity score (empty file zero, complex > simple, fresh file works, clamped to [0,1])
  - Composite weights default includes complexity, sums to 1.0

### Changed
- **Default `carmack_composite_weights`** updated to 6 signals:
  - Before: `kalman 0.25, wavelet 0.20, crash 0.25, coupling 0.15, churn 0.15` (sum 1.00)
  - After:  `kalman 0.20, wavelet 0.15, crash 0.20, coupling 0.15, churn 0.15, complexity 0.15` (sum 1.00)
  - Crash (KM survival) reduced from 0.25 to 0.20 to make room for complexity.
  - Backward compatible: if user's `.forge/config.json` has only 5 weights,
    complexity defaults to 0 (no contribution to score). Use `cw.get("complexity", 0.0)`.

- **`predict_carmack()` integration**: computes complexity per file before
  composing the score. `r["complexity"]` exposed in result dicts.

### Why rc1 (not 1.3.0 final)
The cycle 14 case-study test (N≥200 on E7-filtered + cold-start cases) is
**not yet run**. v1.3.0 final will land after empirical validation that
adding complexity signal:
- Improves `forge --carmack` precision@10 above the cycle 13 v4 baseline (0.28 train)
- Beats `forge --predict` (which beat carmack 64% vs 28% in cycle 13 v4)
- Calibration delta AUC ≥ +0.05 on holdout (cycle 13 v4 was −0.021)

If cycle 14 fails to validate, this rc1 stays rc1 forever (no v1.3.0 release).
If cycle 14 validates, rc1 → v1.3.0 final.

### Internal
- mypy --strict forge.py: Success no issues
- pytest tests/: 262 passed (16 new cycle 14 + 246 existing)
- Branch `feat/cold_start_complexity` → PR → CI 9/9 → merge → tag v1.3.0rc1

### Reference
- McCabe T. (1976), "A Complexity Measure", IEEE TSE
- Halstead M. (1977), "Elements of Software Science"
- Menzies T., Greenwald J., Frank A. (2007), "Data Mining Static Code
  Attributes to Learn Defect Predictors", IEEE TSE — empirical validation
  that static metrics predict defects independently of history.

## [1.2.5] - 2026-05-11

Doc-only patch. Updates **"Honest Limits"** section in README with
cycle 13 v4 case-study verdict (E7-filtered, N=46 effective, **1/3 OUI**).
Supersedes cycle 12 v3 verdict (0/3 OUI on N=37 cold-start panel).

### Changed
- README "Honest Limits" section updated v3 → v4:
  - **C1 OUI ✓ FIRST TIME** in 4 cycles: Fisher p=0.0488 (forge 7/25 vs random 1/25)
  - C2 NON: precision@10 = 0.28, Wilson CI [0.143, 0.476]
  - C3 NON: delta AUC holdout −0.021 (calibration dégrade)
  - E7 filter requires ≥3 bugfix commits on change_file before PRE_BUG
  - Corrects cycle 12 cold-start tautologic verdict

- **Major finding documented**: `forge --predict` (churn-only) BEATS
  `forge --carmack` (5-signal composite) 64% vs 28% top10 on train,
  71% vs 52% on holdout. The simpler predictor wins on E7-filtered
  panel. Multi-signal composite likely dilutes pure churn signal.

- **Calibration convergence v3+v4 on coupling-dominant**: ML calibration
  at N≥20 converges towards coupling 0.45-0.59 dominant (vs heuristic
  0.15). Suggests the heuristic mis-weights the strongest non-history
  signal.

- **Cold-start blind spot acknowledged**: forge --carmack history-based,
  fails on files with 0 prior bugfixes. Cycle 14 (in prep) will add
  complexity-based cold-start signal (McCabe + Halstead, Menzies 2007).

### Unchanged (intentional)
- **Default heuristic weights unchanged**: `(kalman 0.20, wavelet 0.15,
  crash 0.25, coupling 0.15, churn 0.25)`. Calibration not robust
  enough at N=25 to commit a swap.
- No code change in `forge.py`. Pure doc patch with v4 verdict.

### Recommended usage (added to README)
- `forge --predict` for production defect ranking (validated 64-71% top10)
- `forge --carmack` as research mode (composite under investigation)
- `forge --mutate` for AST-aware mutation testing (validated cycle 8)
- `forge --modularity` for architecture monitoring

### Cycle 14 in preparation
Cold-start complexity module (McCabe + Halstead) being implemented
in branche `feat/cold_start_complexity`. Will land as `v1.3.0-rc1`
when CI greens.

## [1.2.4] - 2026-05-11

Doc-only patch. Updates **"Honest Limits"** section in README with
cycle 12 v3 case-study verdict — **N=37 effective, 0/3 criteria OUI**.
Supersedes cycle 11 v2 verdict (1/3 OUI on N=15).

### Changed
- README "Honest Limits" section updated v2 → v3:
  - N=20 train + N=17 holdout (vs N=8+7 in v2)
  - All 3 criteria NON (vs C2 OUI in v2)
  - C1 Fisher p=0.72 (forge 6/20 vs random 4/20 — no signal at N=20)
  - C2 precision@10 = 0.30, Wilson CI [0.146, 0.519]
  - C3 delta AUC holdout +0.039 (sous +0.05 mais positif vs v1's -0.054)
  - Decision matrix verdict: `forge_au_niveau_hasard`
  - Cold-start blind spot documented: forge --carmack signals all 0
    on modules with 0 prior bugfixes (thefuck rules pattern)
  - Calibration NOT robust at N: v2 favors crash+kalman, v3 favors
    coupling. Different optima at different N → signal not stable.
  - Recommended use case: established codebases with ≥1 year of fix
    commits per module. Not reliable on fresh modules / new projects.

### Unchanged (intentional, per D9 anti-bullshit)
- **Default heuristic weights unchanged**: `(kalman 0.20, wavelet 0.15,
  crash 0.25, coupling 0.15, churn 0.25)`. Calibration v3 (coupling
  0.59 dominant) differs from v2 (crash 0.50 + kalman 0.35) → not
  robust at N=20 to commit.
- No code change in `forge.py`. Pure doc patch updating the v2 verdict
  with the more rigorous v3 verdict (N×2.5, all 6 sub-cmds per case
  including --locate with active coverage setup vs v2's --locate skip).

### Internal — process discipline
- Charter D9 (admit losses) honored: the v3 verdict (0/3 OUI) is
  WORSE than v2 (1/3 OUI) but published prominently. Hiding the
  cycle 12 result while keeping the v2 "Honest Limits" claim would
  be mensonge par omission.
- v2 C2 OUI is now understood as favorable signal by chance at small
  N=8 with bug-prone project mix. v3 N=20 with diverse panel
  (including cold-start cases) shows no robust signal.

### Cycle 13 prospects
If Sky agrees, cycle 13 could test N≥100 with panel **filtered by
bugfix history ≥ 1** (within carmack's original scope as history-based
predictor). NOT p-hacking since this scope is what carmack is designed
for. Would clarify if forge has a real signal on its intended use case.

## [1.2.3] - 2026-05-11

Doc-only patch. Adds **"Honest Limits"** section to README with
cycle 11 v2 case-study verdict on `forge --carmack`. v2 supersedes
cycle 11 v1 INVALID (process bâclage, see [forge-case-studies REVERT commit](https://github.com/sky1241/forge-case-studies/commit/0b55e2a)).

### Added
- README "Honest Limits" v2 section with chiffres pre-registered:
  - N=15 effective (8 train + 7 holdout), 400 candidates exhaustively filtered
  - **C2 OUI** ✓ : precision@10 = 0.625, Wilson 95% CI lower 0.306 ≥ 0.30
  - C1 NON : Fisher p=0.31 (forge 5-vs-2 random, N=8 underpowered)
  - C3 NON : delta AUC holdout +0.0095 (below +0.05, but NOT overfitting
    like v1's -0.054)
- Unexpected finding documented: `forge --predict` (churn-only) beats
  `forge --carmack` (multi-signal) 6/8 vs 5/8 top10 on train. Multi-signal
  aggregation may dilute pure churn signal. Under investigation cycle 12.

### Unchanged (intentional)
- **Default heuristic weights unchanged**: `(kalman, wavelet, crash,
  coupling, churn) = (0.20, 0.15, 0.25, 0.15, 0.25)`. Calibration grid
  search on N=8 train suggests crash+kalman dominate (sum 0.85) but
  signal too weak on N=8 to commit (delta AUC holdout below threshold).
- No code change in `forge.py`. Pure doc patch. Cycle 12 (N≥50) will
  re-test for definitive verdict.

### Internal
- Charter D9 (admit losses): cycle 11 v2 verdict `signal_faible_non_concluant`
  (1/3 OUI) reported transparently. The signal_faible classification
  per pre-registered decision matrix (in forge-case-studies/criteria.md)
  triggers "garder outil + heuristic + doc" — exactly this patch.

## [1.2.2] - 2026-05-10

Patch release. End-to-end test pass over all 30 sub-commands caught
**a second production bug** (after the v1.2.1 hook fix): `find_tests`
didn't exclude virtualenv directories.

### Fixed
- **`find_tests` excludes `.venv`/`venv`/`env`/`.tox`/`.eggs`/
  `build`/`.mypy_cache`/`.pytest_cache`** — caught running
  `forge --locate` on the forge repo itself: pytest crashed at
  collection on `.venv/lib/python3.13/site-packages/libcst/tests/
  test_fuzz.py` (third-party test, not for the host harness).
  Pre-1.2.2 only the legacy set [`.forge`, `__pycache__`, `.git`,
  `node_modules`] was excluded.
- **Match exclusions as `/{dir}/` segments**, not bare-name
  substrings. Caught self-inflicted false-positive mid-fix:
  bare `"build"` substring matched FILE names like
  `build_tests.py` (a legitimate test file naming convention,
  cycle 2 cousin pc1 finding from mkdocs). Now uses the
  `/{dir}/` pattern same as `/bench/` exclusions, which only
  matches an exact directory segment in the path.
- **3 regression tests** in `TestCycle10VenvExclusion`:
  `.venv` excluded, `venv` (no dot) excluded, `.tox` /
  `.mypy_cache` / `.pytest_cache` excluded.

## [1.2.1] - 2026-05-10

Patch release. End-to-end runtime test of the v1.2.0 hook caught a
**production bug** that the unit-level regression tests had missed:
the hook was unusable on any real install.

### Fixed
- **`forge --install-hook` now embeds `sys.executable`** and invokes
  `python -m forge` instead of bare `forge`. Pre-1.2.1, the hook
  was `exec forge --fast-deep`. Git invokes pre-commit hooks with
  a stripped PATH that doesn't include the user's venv — so the
  hook crashed with `forge: not found` on every real commit. Caught
  on cycle 9 follow-up by an end-to-end runtime test (cycle 9 unit
  tests covered install/uninstall paths but never actually triggered
  the hook via `git commit`). Sky's RULE 4 lesson re-applied:
  unit-tests-pass ≠ end-to-end works.
- **New regression test** `test_install_hook_embeds_sys_executable`
  pins both the absolute python path embed AND the `python -m forge`
  invocation form (not bare `forge`).

## [1.2.0] - 2026-05-10

Minor release. Closes the orchestration gap between forge's ~25
sub-commands. Pre-cycle 9, each sub-command was an island. Now
`forge --shield` chains them with a feedback edge (Stage 1 carmack
output drives Stage 2 gen_props target selection). Also adds a
git pre-commit hook installer to remove the adoption barrier.

### Added
- **`forge --shield`** — orchestrator with feedback chain. Stage 1:
  `predict_carmack` → top-3 risky files. Stage 2: `gen_props` on
  risky files lacking tests (skip test_*.py files; cycle 9 caught
  carmack ranking by churn → test files ranking high → gen_props
  on a test file is nonsense — filtered). Stage 3: `fast_deep` →
  run impacted tests. (cycle 9 L-2)
- **`forge --install-hook`** — install a forge-managed git
  pre-commit hook at `.git/hooks/pre-commit`. Idempotent (re-install
  on top of forge hook is no-op). Refuses to clobber a non-forge
  hook unless `--force` (which backs up to `pre-commit.bak`).
  (cycle 9 L-1)
- **`forge --uninstall-hook`** — remove a forge-managed pre-commit
  hook. Refuses to delete a hook without the forge sentinel comment
  (won't clobber hand-edited hooks). Auto-restores `pre-commit.bak`
  if one exists.
- **`_has_test_for(root, src_file)`** — AST-based check of whether
  any test file imports a source module. Cycle 7 L-1 lesson applied:
  no substring matching, walks `Import` and `ImportFrom` nodes only.

## [1.1.0] - 2026-05-09

Minor release. Adds `forge --fast-deep` for transitive impact-based
test selection, fixes a long-standing false-positive/negative bug in
`find_impacted_tests` (B23). Also incorporates the cycle 6
`--incremental-mutate` innovation (sky-master Round 1 winner).

### Added
- **`forge --fast-deep`** — Bazel/Buck-style transitive closure on
  the inverted import graph. When a leaf changes, every test that
  transitively depends on it is selected. Two safeguards:
  `fast_deep_max_depth` (default 5, BFS hop cap) and
  `fast_deep_fanout_cap_pct` (default 80, falls back to full suite if
  selection > 80% of total tests). Both cfg-tunable. (cycle 7 L-2)
- **`forge --incremental-mutate`** — libcst AST-diff based mutation
  that mutes only the nodes added/modified between HEAD and a
  baseline commit. Speedup vs full `--mutate` is proportional to the
  diff size. (cycle 6 sky-master, merged from feat/incremental-mutate)

### Fixed
- **`find_impacted_tests` substring matching → AST-based imports
  (B23)** — pre-1.1.0, the impact detector used `if mod in content`
  which produced both:
    - false positives (a test mentioning the module name only in a
      comment / docstring was flagged as impacted), and
    - false negatives (`from X import Y as Z` then uses of `Z`
      left no `X` token visible to substring matching).
  Now walks `ast.parse` looking at `Import` and `ImportFrom` nodes,
  resolves dotted-import paths so a change to `pkg/sub.py` matches
  `from pkg.sub import X` and `import pkg.sub`. Conservative
  fallback: tests with syntax errors are treated as impacted (better
  surface than silently skip). (cycle 7 L-1)

### Internal
- forge.py 4400+ LOC, 231 default + 1 slow tests pass on Linux/
  macOS/Windows × Python 3.11/3.12/3.13.
- Coverage 77%+ via cycle 5 K-6 fault_locate end-to-end test.
- Zero `# type: ignore` actif in forge.py.
- mypy --strict passes cross-version (1.20.x + 2.0.x) and
  cross-platform (--platform=linux/win32/darwin).

## [1.0.4] - 2026-05-08

Patch release that addresses 4 findings caught by the deep 4-agent
audit (cousin pc1 + sky-master independent), plus a coverage gap
on `fault_locate`'s display path. Cycle 5 Phase K closure.

### Fixed
- **Exit code consistency on `--paths-to-mutate` (B20)** — non-existent
  path or path-outside-repo now exit `2` (CLI usage error convention),
  not `1` (which is reserved for "command ran but failed", e.g.
  mutation score below threshold). Same class as `forge --frobulate`
  → exit 2. (cycle 5 K-2)

### Added
- **`--modularity` Q-thresholds are now cfg-tunable (B17)** — added
  `modularity_q_good_threshold` (default 0.30, Newman 2006) and
  `modularity_q_poor_threshold` (default 0.15) to
  `FORGE_CONFIG_DEFAULTS`. Override in `.forge/config.json` for
  stricter or looser team policies. Result dict surfaces the
  thresholds so the print report formats from a single source of
  truth. (cycle 5 K-4)
- **README "All subcommands" table now lists cycle 5 features (B21)** —
  `forge --modularity` and `forge --mutate --paths-to-mutate FILE`
  added; the implicit "this is every public sub-command" claim is
  honest again. (cycle 5 K-3)
- **Symlink boundary regression test (B16)** — pins that
  `forge --mutate --paths-to-mutate <symlink-pointing-outside-repo>`
  rejects with exit 2 + "must point to a file inside the repo".
  Path traversal protection was already there via
  `Path.resolve().relative_to(root)`; this commit locks the contract.
  (cycle 5 K-5)
- **`fault_locate` end-to-end display test** — covers the SBFL
  computation + suspect rendering + label band path that was
  previously only exercised on the negative case. Coverage 74% → 77%.
  (cycle 5 K-6)

### Internal
- **B-2 venv drift admitted and resolved locally** — `pip install -e .
  --force-reinstall --no-deps` post-bump procedure documented in
  cycle 6+ engagement (auto-audit cousin pc1 doc).
- **Auto-audit + 4-agent deep audit conducted** — produced
  `~/forge-auto-audit-cycle3-4-5.md` (1 agent, 527 lines, 7.5/10) and
  `~/forge-deep-audit-cousin-2026-05-08.md` (4 agents, 8.4/10). The
  multi-agent revealed 4 findings the solo audit missed (B19 main god
  func, B20 exit code, B21 README, B22 G-1 optimism), validating the
  multi-agent pattern for future releases.

### Out of scope (cycle 6 candidates)
- B19 `main()` god-function 242 LOC + 18 if/elif blocks → refactor
  argparse / dict-handler. Tech debt, not a bug.
- B22 G-1 "expected green" optimistic claim → retroactive lesson
  learned, not fixable.

## [1.0.3] - 2026-05-08

Patch release that brings the suite green on the full
GitHub Actions matrix (3 OS × 3 Python = 9 jobs). The v1.0.2 claim
"PyPI publishable" was true on Linux; v1.0.3 makes it true on
Windows and macOS as well. Three Phase J commits caught by the
first live CI runs (`acd5c69` workflow + 3 follow-up patches).

### Fixed
- **Cross-platform path comparisons in `find_tests`** — pre-1.0.3
  `find_tests` built `excludes` with `os.sep` but compared with
  `str(t)`. On Windows, `Path.glob` can return paths whose `str()`
  uses forward slashes (depending on construction); the substring
  match silently failed and `norecursedirs` exclusions were ignored.
  Now both sides use forward-slash via `Path.as_posix()` and
  literal `"/dir/"` excludes. Linux/macOS unchanged. (cycle 4 J-2,
  B13 forge.py side)
- **Test assertions normalize paths via `as_posix()`** — 8 sites in
  `tests/test_forge_real_algos.py` did
  `"foo/bar.py" in str(f)` which broke on Windows for the same
  reason. Replaced with `f.as_posix()` so the comparison string is
  always forward-slash, regardless of platform. (cycle 4 J-1, B13
  test side)
- **`git commit` calls now set `user.email`/`user.name`** — two raw
  test sites (`test_bisect_verify_step_has_timeout`, 
  `test_bisect_test_handles_git_log_failure`) did
  `git init` + `git commit --allow-empty` without configuring git
  user. On a fresh CI runner without `~/.gitconfig`, that exits 128
  ("Author identity unknown"). Linux + Windows runners affected;
  macOS runners ship a default config. Now both sites either call
  the existing `_git_init` helper or invoke `git config` inline.
  (cycle 4 J-1, B14)
- **`fcntl` import is now `sys.platform`-narrowed** — pre-1.0.3
  `log_run` used `try: import fcntl except ImportError` for the
  Windows fallback. The runtime worked, but mypy strict on Windows
  surfaced 4 attr-defined errors because the typeshed Windows stub
  resolves the module name without exposing POSIX-only `flock`,
  `LOCK_EX`, `LOCK_UN`. The `if sys.platform != "win32":` form lets
  mypy treat the fcntl branch as dead code on Windows; zero
  `# type: ignore` added. (cycle 4 J-3, B15)

### Internal
- **GitHub Actions CI live across 9 jobs** (Linux/macOS/Windows ×
  Python 3.11/3.12/3.13). Workflow at `.github/workflows/test.yml`,
  badge in README is dynamic. Initial runs caught B13/B14/B15
  before they reached PyPI. (cycle 4 G-1 / acd5c69)

## [1.0.2] - 2026-05-08

Patch release that fixes a cross-version mypy strict regression
caught immediately after v1.0.1 was tagged. The v1.0.1 claim "mypy
strict pass" only held on a venv where pytest-timeout wasn't
installed AND mypy was 2.0. On a fresh clone with `[dev]` extras
(pytest-timeout installed) and mypy 1.20.x, the strict-mode
test_mypy_strict_on_forge failed with two errors at the
pytest-timeout import.

### Fixed
- **`pytest-timeout` import probe is now stdlib-typed** —
  `importlib.util.find_spec("pytest_timeout")` replaces the
  `try: import pytest_timeout` + `# type: ignore[import-not-found]`
  pair that broke under mypy 1.20.x when the package was installed
  without stubs. Combined-code ignores (e.g.
  `[import-not-found,import-untyped]`) didn't help either: whichever
  code didn't fire on a given env triggered `unused-ignore` under
  strict mode. find_spec sidesteps the whole class of issues.
  (cycle 4 H6, B12)
- **Zero `# type: ignore` left in forge.py.** The L958 site was the
  last one; the comment block at L955-961 documents the rationale
  for the find_spec swap so a future reader doesn't reach for the
  bare-import pattern again.

## [1.0.1] - 2026-05-08

Patch release that fixes 8 audit findings caught after v1.0.0 was
tagged. The big one: `forge --mutate` and `forge --locate` now exit
non-zero when their optional dep is missing (was exit 0 — silently
breaking CI scripts shaped like `forge --mutate && deploy`). Also
adds a real `--version` flag and tightens user-facing UX/docs.

### Fixed
- **`forge --mutate` and `forge --locate` exit non-zero** when their
  optional dep (libcst / coverage+pytest-cov) is missing. Pre-1.0.1
  the install hint printed but exit code was 0 — a CI script using
  `&&` chaining would proceed silently. (cycle 4 H-1, B1)
- **`fault_locate` signature** changed from `-> None` to `-> bool`
  so callers can branch on dep-missing vs dep-present. (cycle 4 H-1)
- **User hints "Run: forge.py --init / --baseline"** now correctly
  say `forge --init` / `forge --baseline` (the entry point installed
  by `pip install`, not the run-from-checkout invocation).
  (cycle 4 H-3, B3)
- **`find_repo_root` fall-through** now warns explicitly when no
  `.git/` is found walking up. Previously silent → users got cryptic
  "Git not available" lines mid-output for --carmack/--predict/etc.
  (cycle 4 H-3, B4)
- **`.forge/config.json` decode failure** now prints a Warning and
  uses defaults. Was silent → users assumed their config was loaded
  while in reality every knob was at default. (cycle 4 H-3, B5)
- **`init_repo` `write_text`** sites now pass `encoding="utf-8"`
  explicitly. On Windows the default was CP1252-locale-dependent.
  (cycle 4 H-3, B7)

### Added
- **`forge --version`** prints `forge-shield X.Y.Z` and exits 0.
  Sourced from `importlib.metadata.version("forge-shield")` so it
  can never drift from `pyproject.toml`. Two defensive fallbacks:
  `0.0.0-dev` for run-from-checkout, `unknown` for embed contexts.
  (cycle 4 H-2, B2)
- **README "All subcommands" table** lists the 16 most-used
  invocations with one-line descriptions; trailer points at
  `--help` for the full flag list. (cycle 4 H-5, B8)
- **Subprocess test suite for fail-fast exit codes**: 3 new tests
  in `tests/test_cli_entry_point.py` (mutate-without-libcst,
  locate-without-coverage, --version) using a throwaway venv with
  forge installed core-only. Real-behavior tests, not source-greppy.
  (cycle 4 H-1 + H-2)
- **`@pytest.mark.skipif(sys.platform == "win32")`** on
  `test_log_run_concurrent_writes_keep_line_integrity` so the
  Windows CI matrix (Phase G) doesn't go red on a known-deferred
  fcntl gap. (cycle 4 H-4, B6)

### Changed
- **`Development Status` classifier** bumped from `4 - Beta` to
  `5 - Production/Stable`. Was kept Beta in v1.0.0 to respect the
  "no drive-by" constraint of the release commit. (cycle 4 H-5, B10)
- **`pytest-cov` install hint** in `fault_locate` now points at the
  cycle 4 E-2 extra: `pip install 'forge-shield[locate]'`. (cycle 4 H-1)

## [1.0.0] - 2026-05-08

First public PyPI release. Bundles the full cycle 4 work — type hints
on every top-level function, libcst-based mutation backend, granular
install extras, CLI validator, atomic JSON writes, and a documented
matrix of subcommand → extra mappings. Suite at 205 default + 1 slow,
mypy `--strict` passes the entire codebase.

### Added — Cycle 4 E-2 (2026-05-08)
- **Granular install extras** in `pyproject.toml`:
  - `forge-shield[mutate]` → libcst (`forge --mutate`, AST-aware backend)
  - `forge-shield[locate]` → coverage + pytest-cov (`forge --locate`, Ochiai SBFL)
  - `forge-shield[fuzz]` → hypothesis (`forge --gen-props`; the user runs the
    generated tests, hypothesis is needed to execute them)
  - `forge-shield[all]` → meta-extra rolling up `[mutate,locate,fuzz]`
  - `forge-shield[dev]` → contributor extra (rolls in `[all]` plus pytest,
    pytest-timeout, mypy, mutmut)
- **Default `pip install forge-shield`** now ships only stdlib + the user's
  own pytest. Each subcommand that needs a native lib lives behind its own
  extra; users opt in to what they actually run.
- Fail-fast clean errors when an extra is missing (cohérent across the
  matrix): `forge --mutate` without `[mutate]` and `forge --locate` without
  `[locate]` print an install hint and exit cleanly instead of stack-tracing.

### BREAKING — Cycle 4 D-3b (2026-05-08)
- **Mutation backend is now libcst (AST-aware) only.** The regex
  backend was removed after D-3b runtime validation showed 23.4%
  invalid mutants on real repos (filelock, attrs, mistune;
  100/427 mutants were `SyntaxError`-only "kills") vs 0/133 for
  libcst. See [`docs/D3B_RUNTIME_VALIDATION.md`](docs/D3B_RUNTIME_VALIDATION.md).
- **`FORGE_MUTATION_BACKEND` env var removed.** It selected
  between `auto` / `libcst` / `regex`; with regex gone there's
  nothing to switch. If the var is set in user CI scripts, it's
  ignored silently.
- **`forge --mutate` requires libcst.** libcst is an OPTIONAL
  runtime dependency to keep the install footprint small for
  the ~80% of users who don't run `--mutate`. Install via
  `pip install 'forge-shield[mutate]'`. Without it,
  `forge --mutate` exits cleanly with an install-message rather
  than a stack trace. All other forge subcommands work without
  libcst.

### Added — Cycle 4 (2026-05-08)
- **Type hints** on every top-level function (64 + 4 nested) — `mypy --strict`
  passes on both mypy 1.20.x and 2.0. Test `tests/test_typing.py` enforces
  this as a `@pytest.mark.slow` regression.
- **`.forge/config.json`** now consumes 21 user-tunable knobs (was 11
  pre-cycle 4): mutation threshold, ochiai top-N, kalman Q/R, KM horizon,
  hamming severity thresholds, ochiai label cutoffs, carmack composite
  weights, full-cycle small-file LOC threshold, plus all subprocess
  timeouts (test_runner, pytest_per_test, bisect, impacted, snapshot).
  See [`docs/CYCLE2_SUMMARY.md`](docs/CYCLE2_SUMMARY.md) for the rationale.
- **CLI validator** `_validate_args`: rejects unknown flags with `did you
  mean` hint via difflib, type-checks numeric flags, requires values for
  value-flags (`--mutate`, `--bisect`, `--close`, `--minimize`, `--gen-props`,
  `--snapshot`, `--add`, `--weeks`), accepts `--key=value` argparse style.
- **Atomic `save_json`** via tempfile + `os.replace` — Ctrl+C / power
  loss mid-write no longer truncates baseline / report JSON.
- **fcntl-locked `log_run`** on POSIX for safe concurrent writes
  (`forge --watch` + `forge --fast` from another shell). Falls back to
  best-effort append on Windows (no `fcntl`).
- **`_run_git_full(timeout=30)`** helper + migrated 11 bare `subprocess.run(["git", ...])`
  callsites in `bisect_test` and `get_changed_files` so a frozen git
  can't hang forge forever.
- **Dedupe helpers**: `_pytest_cmd`, `_minmax_normalize`, `_parse_iso`
  centralize patterns previously inlined at 6 / 4 / 5 sites.
- **`@pytest.mark.slow` marker** registered in pyproject; `addopts =
  "-m 'not slow'"` excludes slow tests from the default suite (mypy
  strict subprocess test currently the only one).

### Fixed — Cycle 4
- **`fault_locate` L2890** dead-branch comparison `list == set` (mypy
  strict caught the never-True equality check). Defensive code that
  never triggered, but the dead branch was confusing.
- **`forge --mutate=` / `--bisect=`** with empty value after `=` ran
  mutation on the wrong file. Now rejected at `_validate_args`.
- **`predict_horizon_weeks` config** ignored by main()/full_cycle (6
  sites of `weeks=8` hardcoded short-circuited cfg lookup). Now passes
  `weeks=None` so the function-side cfg-default kicks in.
- **`forge --watch`**: refactored inner loop into `_watch_iteration`
  helper with per-file OSError catch on `read_bytes` (vim swap race).
- **`run_mutation`**: extracted `_try_one_mutant` so the apply-mutant /
  finally-restore contract is testable in isolation. Original source
  is restored even on KeyboardInterrupt / SystemExit / OSError mid-write.
- **`_kaplan_meier`** legacy-shape narrowing: per-element isinstance
  loop accepts `list[float]` and `list[tuple[float, bool]]` cleanly
  across mypy 1.X / 2.X.
- **`add_bug`** signature corrected from `-> None` to `-> str` (drift
  docstring↔return that mypy strict caught).
- **`_validate_args` numeric flag completeness**: full coverage
  (`forge --weeks abc` → exit 2 with type error). Was 80% pre-cycle 4.

### Changed — Cycle 4
- **`requires-python`** bumped from `>=3.10` to `>=3.11`. forge.py uses
  `tomllib` (stdlib only on 3.11+); the 3.10 fallback was a silent
  empty-dict path that hid the real dependency.
- **classifiers**: dropped Python 3.10, added Python 3.13 to match.
- **dev deps**: added `mypy>=1.0` and `pytest-cov>=4.0` (the latter
  was implicitly required by the cycle-3 coverage instrumentation tests
  but wasn't declared).
- **Config keys**: `cfg["predict_horizon_weeks"]` now properly flows
  through main() and full_cycle dispatchers. Test
  `TestCycle4P11WeeksFlowsThroughDispatch` enforces.
- **`os.path` → `pathlib`** in 3 sites (`log_run` parent dir creation,
  `fault_locate` basename derivation). String-template generated code
  in `gen_props` keeps `os.path` for backward-compat with target users.

### Removed — Cycle 4
- **`PREDICT_WEIGHTS` module-level constant** — was a duplicate of
  `FORGE_CONFIG_DEFAULTS["predict_weights"]` and never referenced by
  forge.py code. Single source of truth.
- **`HEATMAP_FILE` constant** — declared but never consumed (was a
  placeholder for a `show_heatmap` save target that never materialized).
- **`_is_destructive_function(node, source_text)` `source_text` arg** —
  parameter was never read inside the function body. 20+ test sites
  updated via sed.
- **Lazy imports promoted to top-level**: `difflib`, `tempfile`, `shlex`
  (each at 1-2 inner-scope sites). `fcntl` and `tomllib` stay lazy
  (OS-/version-conditional).

### Internal — Cycle 4
- Suite went **141 → 198 tests** across cycle 4 (+57 net).
- Coverage measurable for the first time (cycle 3 `tests/conftest.py`
  fix); now ~73% reported by `pytest --cov=forge`.
- 17 + 5 commits this cycle (P1-P11, Phase B, C-A, C-B, C-B-fix, C-C, D-1, D-2).
- 1 `# type: ignore[import-not-found]` justified (`pytest_timeout`,
  optional dep, no published stub).

## Earlier cycles

- **Cycle 3** — chunked refactor (coverage baseline → CLI validation).
  See [`docs/CYCLE2_SUMMARY.md`](docs/CYCLE2_SUMMARY.md) and
  [`docs/CYCLE3_BATTLE_PLAN.md`](docs/CYCLE3_BATTLE_PLAN.md).
- **Cycle 2 (+ 2.5)** — auto-improvement via inter-Claude canal v0.5
  on real-world repos (mistune, anyio, marshmallow, black, pytest, mkdocs).
  See [`docs/CYCLE2_SUMMARY.md`](docs/CYCLE2_SUMMARY.md).
- **Cycle 1** — initial `forge` extraction from MUNINN-internal tooling.
  See git history `34f53ca` ↔ `bf44660` (2026-05-07).

[Unreleased]: https://github.com/sky1241/forge/compare/v1.2.2...HEAD
[1.2.2]: https://github.com/sky1241/forge/releases/tag/v1.2.2
[1.2.1]: https://github.com/sky1241/forge/releases/tag/v1.2.1
[1.2.0]: https://github.com/sky1241/forge/releases/tag/v1.2.0
[1.1.1]: https://github.com/sky1241/forge/releases/tag/v1.1.1
[1.1.0]: https://github.com/sky1241/forge/releases/tag/v1.1.0
[1.0.4]: https://github.com/sky1241/forge/releases/tag/v1.0.4
[1.0.3]: https://github.com/sky1241/forge/releases/tag/v1.0.3
[1.0.2]: https://github.com/sky1241/forge/releases/tag/v1.0.2
[1.0.1]: https://github.com/sky1241/forge/releases/tag/v1.0.1
[1.0.0]: https://github.com/sky1241/forge/releases/tag/v1.0.0
