# forge

[![Tests](https://github.com/sky1241/forge/actions/workflows/test.yml/badge.svg)](https://github.com/sky1241/forge/actions/workflows/test.yml)
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/sky1241/forge)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Pytest regression shield with predictive analytics for Python repos. Single-file core, stdlib-only runtime (pytest is the only required dep — bring your own).

```bash
pip install forge-shield
forge --init     # scaffold .forge/ and BUGS.md
forge --baseline # snapshot current test suite
forge            # detect regressions vs baseline
forge --carmack  # rank files by predicted defect risk
forge --shield   # orchestrate: predict → gen tests → run impacted
```

## How it compares to industry tools (cycle 8 bench, see [BENCHMARK.md](BENCHMARK.md))

| Job | forge | Industry tool | Result |
|---|---|---|---|
| Mutation testing — `httpie/cli/argparser.py` | `--mutate` (libcst, 70 mutants) | `mutmut` (regex, 301 mutants) | **forge 100% kill in 11min** vs mutmut 33% in 16min |
| Test impact selection on import-graph change | `--fast-deep` (Bazel-style transitive) | `pytest --testmon` (coverage-based) | testmon wins warm; **fast-deep wins cold-start CI** (no `.testmondata` to maintain) |
| Architecture quality metric | `--modularity` (Newman-Girvan Q) | `pydeps` (graph extraction) | **forge unique** — pydeps has no Q metric |

See [BENCHMARK.md](BENCHMARK.md) for the 6 frictions admitted (test set asymmetry, mutmut crash, black skipped per timeout cap).

## Honest Limits — full cycles 11→21 v8 (2026-05-12)

forge has been tested through 10+ pre-registered scientific cycles on
BugsInPy real Python bugs. Full methodology + verdicts public on
[forge-case-studies](https://github.com/sky1241/forge-case-studies).

### Production-validated capabilities

- **`forge --predict`** (Nagappan-Ball ICSE 2005, churn-only) :
  **recommended primary defect predictor**. 54-71% precision@10 holdout
  on E7-filtered scope (≥3 bugfix history). Beats multi-signal composite
  in 3 independent cycles (11 v2, 13 v4, 15 v6).
- **`forge --carmack`** (6-signal composite) : research mode, weights
  heuristic non-validated. Cycle 15 verdict 1/3 OUI (C1 Fisher p=2.5e-9
  very robust ; C2 plafond ~45% global). Cycle 19 v2 ablation drop
  kalman+wavelet = **ambigu** (TH +2.3 / REF -16.7 pts, populations
  partially disjoint 50% overlap, hétérogénéité per-projet majeure).
  Keep 6-signal composite = conservative default.
- **`forge --modularity`** : Newman-Girvan Q architecture metric,
  validated cycle 8 vs pydeps.
- **`forge --mutate`** : libcst AST-aware mutation testing, validated
  cycle 8 vs mutmut (100% kill in 11min vs mutmut 33% in 16min on
  httpie/cli/argparser.py).
- **`forge --gen-props` / `--minimize` / `--snapshot` / `--watch` /
  `--bisect` / `--flaky`** : validated cycle 20 v2 on 30 real cases
  (5 projects × 6 tools, 100% ratio_ok with graceful exits).

### Production-ready in v2.1.0 (was research-mode in v2.0.0)

- **`forge --locate`** : `--exclude-system-libs` default ON since v2.1.0
  filters site-packages / .venv / stdlib from SBFL ranking. Now usable
  on real projects. Pass `--include-system-libs` to restore v2.0.0
  legacy behavior.
- **`forge --shield`** : now prints `[SHIELD WARNING]` + `[SHIELD HINT]`
  on carmack short-circuit instead of silent skip (v2.1.0). Use
  `--weeks-from <ISO_DATE_OR_SHA>` to anchor history window to a
  historical commit instead of system date (fix BUG-014). Works on
  active and dormant projects when window is anchored properly.

### Honest findings cycles 11→20

| Cycle | Hypothesis | Verdict | Note |
|---|---|---|---|
| 11-15 | forge --carmack baseline calibrations | 1/3 OUI (cycle 15 strongest) | Fisher p=2.5e-9 (C1) but plafond C2 |
| 16 v1+v2 | Cold-start AST similarity signal | REJECTED (drop signal) | Jaccard quasi-uniform on Python files |
| 17 | forge --locate at scale | REJECTED user-facing | SBFL ranks system files w/o filter |
| 18 v2 | forge --shield on HEAD actuel | OUI conditional | 11/11 active, 0/9 dormant |
| 19 v2 | Composite ablation drop kalman+wavelet | **AMBIGU** | Populations disjoint, hétérogène per-proj |
| 20 v2 | Sanity at scale (5+ cases/tool) | **OUI ferme** | 6/6 tools 100% on 30 real cases |

### Known bug — FIXED in v2.1.0

~~`forge --shield` / `forge --carmack` `--weeks N` use system date, not
PRE_BUG commit date.~~ **Fixed in v2.1.0** via `--weeks-from <ISO_DATE_OR_SHA>`.
Pass `--weeks-from 2020-01-15` to anchor window to that date, or
`--weeks-from <git_ref>` to anchor to a commit. See BUGS.md BUG-014.

### Reproducibility

10+ FINAL_REPORTs publicly available with pre-registration committed
before all runs. Seeds 42/43, 44/45, 48/49, 50/51, 52/53, 54/55,
56/57 — all disjoint inter-cycles.

Latest reports:
- [FINAL_REPORT_v12_v2.md](https://github.com/sky1241/forge-case-studies/blob/cycle20_v2/FINAL_REPORT_v12_v2.md) (cycle 20 v2, sanity at scale, 6/6 OUI)
- [FINAL_REPORT_v11_v2.md](https://github.com/sky1241/forge-case-studies/blob/cycle19_v2/FINAL_REPORT_v11_v2.md) (cycle 19 v2, ablation AMBIGU)
- [FINAL_REPORT_v10_v2.md](https://github.com/sky1241/forge-case-studies/blob/cycle18_v2/FINAL_REPORT_v10_v2.md) (cycle 18 v2, shield HEAD actuel)
- [FINAL_REPORT_v9.md](https://github.com/sky1241/forge-case-studies/blob/cycle17/FINAL_REPORT_v9.md) (cycle 17, locate REJECTED)
- [FINAL_REPORT_v8.md](https://github.com/sky1241/forge-case-studies/blob/cycle16_v2/FINAL_REPORT_v8.md) (cycle 16 v2, similarity REJECTED)
- [FINAL_REPORT_v6.md](https://github.com/sky1241/forge-case-studies/blob/cycle15/FINAL_REPORT_v6.md) (cycle 15, C1 p=2.5e-9 robust)
- Earlier cycles 11-14 preserved on forge-case-studies main branch

## What's new (cycle 4)

- **`mypy --strict`** passes the entire codebase (`tests/test_typing.py` enforces).
- **`--mutate`** now uses [libcst](https://github.com/Instagram/LibCST) (AST-aware) — 0 invalid mutants by construction. The previous regex backend produced 23.4% syntax-error noise on real repos (filelock, attrs, mistune); see [`docs/D3B_RUNTIME_VALIDATION.md`](docs/D3B_RUNTIME_VALIDATION.md).
- **Granular install extras**: `[mutate]` / `[locate]` / `[fuzz]` / `[all]` — pay only for the subcommands you use.
- **`.forge/config.json`** consumes 21 user-tunable knobs (mutation threshold, ochiai top-N, kalman Q/R, KM horizon, hamming severity, ochiai cutoffs, carmack composite weights, full-cycle small-file LOC, all subprocess timeouts).
- **CLI validator** rejects unknown flags with a `did you mean` hint via `difflib`.

See [CHANGELOG.md](CHANGELOG.md) for the full picture.

## Installation

### Default (zero deps beyond stdlib + your pytest)

```bash
pip install forge-shield
```

Ships with: `--predict`, `--carmack`, `--baseline`, `--diff`, `--watch`, `--bisect`, `--flaky`, `--snapshot`, `--add`, `--close`, `--fast`, `--heatmap`, `--init`.

### With optional features

```bash
pip install 'forge-shield[mutate]'   # adds --mutate    (libcst-based)
pip install 'forge-shield[locate]'   # adds --locate    (Ochiai SBFL via coverage)
pip install 'forge-shield[fuzz]'     # adds --gen-props (Hypothesis)
pip install 'forge-shield[all]'      # everything above
```

## What it does

- **Baseline & regression detection** — snapshots your pytest results, flags any test that goes from pass to fail.
- **Flaky test detection** — re-runs failures, classifies flaky vs deterministic.
- **Defect-prone file ranking** (`--carmack`) — combines git churn, import coupling and test-failure history into a per-file risk score.
- **Test generation** (`--gen-props`) — emits Hypothesis property tests for pure functions, with a destructive-side-effect AST guard so it never runs `gen_props` on code that writes files or shells out.
- **Mutation testing** (`--mutate`) — libcst (AST-aware) mutator, Offutt 1996 operators (AOR, ROR, LCR, UOI, SDL).
- **Fault localization** (`--locate`) — Ochiai SBFL formula over `coverage.py` data.
- **Delta debugging** (`--minimize`) — ddmin (Zeller 2002) to shrink failing inputs.

### All subcommands

| Sub-command | What it does |
|---|---|
| `forge` | Run tests vs baseline |
| `forge --baseline` | Snapshot the suite |
| `forge --predict` | Rank files by churn-based defect risk |
| `forge --carmack` | Multi-signal risk score |
| `forge --modularity` | Newman-Girvan Q over the import graph |
| `forge --mutate` | Mutation testing (whole repo) |
| `forge --mutate --paths-to-mutate FILE` | Mutation testing scoped to one validated file |
| `forge --locate` | Ochiai SBFL fault localization |
| `forge --gen-props` | Hypothesis property tests |
| `forge --bisect TEST` | Bisect a failing test back to its commit |
| `forge --flaky [N]` | Run tests N times to find flaky |
| `forge --snapshot CMD` | Capture command output as golden |
| `forge --snapshot-check` | Diff against goldens |
| `forge --add "DESC"` | Log a bug in BUGS.md |
| `forge --close BUG-ID` | Mark a bug fixed |
| `forge --watch` | Auto re-run on file change |
| `forge --fast` | Run only directly-impacted tests (1-hop) |
| `forge --fast-deep` | Transitive impact via inverted import graph (Bazel-style) |
| `forge --full-cycle` | Run the full pipeline |

`forge --help` for the complete flag list and examples; `forge --version` to print the installed version.

## Optional features

| Feature | Extra | Backend |
|---|---|---|
| `--mutate` (Offutt 1996 mutation testing) | `[mutate]` | [libcst](https://github.com/Instagram/LibCST) AST-aware |
| `--locate` (Abreu 2007 Ochiai SBFL) | `[locate]` | [coverage.py](https://coverage.readthedocs.io/) + pytest-cov |
| `--gen-props` (Hypothesis property tests) | `[fuzz]` | [hypothesis](https://hypothesis.readthedocs.io/) |

Forge prints a clean install hint (no Python traceback) if you invoke a subcommand without its extra installed — e.g. `forge --mutate` without `[mutate]` says `pip install 'forge-shield[mutate]'` and exits.

## What's actually inside

Algorithms are implemented from the papers, not wrapped from sklearn/scipy/networkx.

| Algorithm | Implementation | Reference |
|---|---|---|
| Louvain community detection | greedy modularity gain, pure Python | Blondel et al. 2008 |
| Newman-Girvan modularity Q | `(1/2m)·Σ[A_ij − k_i·k_j/2m]·δ` | Newman & Girvan 2004 |
| Kaplan-Meier survival | right-censoring, ties handled events-first | Kaplan & Meier 1958 |
| Adaptive Kalman filter | innovation-based variance re-estimation | Mehra 1970 (style) |
| Haar wavelet | textbook avg/diff, padded to power of 2 | — |
| DTW | O(n·m) DP matrix | Sakoe & Chiba 1978 |
| Ochiai SBFL | `failed / sqrt(totalFailed × (passed+failed))` | Abreu et al. 2007 |
| ddmin | unresolved-aware delta debugging | Zeller & Hildebrandt 2002 |

Validation tests pin known results: Karate Club graph Q ∈ [0.38, 0.45] (Zachary 1977), Kaplan-Meier hand-checked survival probabilities, two-cliques+bridge community split.

## Honest limits

- The composite `carmack_score` weights (kalman 0.25, wavelet 0.20, crash 0.25, coupling 0.15, churn 0.15) are **heuristic, not calibrated against a labelled dataset**. Use it as a ranking signal, not a probability.
- The "adaptive Kalman" is innovation-based variance re-estimation, not full Shumway-Stoffer EM with RTS smoother.
- Coverage of forge's own CLI subcommands is partial — the math primitives are well tested, the orchestration code is not.

## Requirements

- Python ≥ 3.11 (uses stdlib `tomllib`)
- pytest (your project's test runner — not bundled with forge)
- Cross-platform: macOS / Linux / Windows. Subprocess calls go through `sys.executable -m pytest` with UTF-8 `errors=replace`.

## License

MIT — see [LICENSE](LICENSE). Changelog: [CHANGELOG.md](CHANGELOG.md).
