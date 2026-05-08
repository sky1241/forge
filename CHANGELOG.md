# Changelog

All notable changes to forge are documented here. Format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/sky1241/forge/compare/0.1.0...HEAD
