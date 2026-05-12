# forge

[![Tests](https://github.com/sky1241/forge/actions/workflows/test.yml/badge.svg)](https://github.com/sky1241/forge/actions/workflows/test.yml)
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/sky1241/forge)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Pytest regression shield with predictive analytics for Python repos.**
Single-file core, stdlib-only runtime (pytest is the only required dep).
Validated across 14 pre-registered scientific cycles on real BugsInPy
bugs — see [Scientific validation](#scientific-validation) below.

---

## Install

```bash
pip install forge-shield                    # default (zero extra deps)
pip install 'forge-shield[mutate]'          # adds --mutate (libcst)
pip install 'forge-shield[locate]'          # adds --locate (coverage.py)
pip install 'forge-shield[fuzz]'            # adds --gen-props (Hypothesis)
pip install 'forge-shield[all]'             # everything above
```

Requirements: Python ≥ 3.11, pytest (your project's test runner — not bundled).
Cross-platform: macOS / Linux / Windows.

## Quickstart

```bash
forge --init        # scaffold .forge/ and BUGS.md
forge --baseline    # snapshot current test suite
forge               # detect regressions vs baseline
forge --predict     # rank files by churn-based defect risk (recommended)
forge --shield      # orchestrate: predict → gen tests → run impacted
```

## Tools

| Sub-command | What it does |
|---|---|
| `forge` | Run tests vs baseline |
| `forge --baseline` | Snapshot the suite |
| **`forge --predict`** | **Rank files by churn-based defect risk (recommended primary)** |
| `forge --carmack` | Multi-signal risk score (research mode) |
| `forge --carmack --weeks-from <ISO_DATE_OR_SHA>` | Anchor history window to a date (cycle 21 BUG-014 fix) |
| `forge --shield` | Orchestrate predict → gen-props → fast-deep |
| `forge --modularity` | Newman-Girvan Q over the import graph |
| `forge --mutate [--paths-to-mutate FILE]` | Mutation testing (libcst AST-aware) |
| `forge --mutate --incremental-mutate --since SHA` | Mutate only files changed since SHA |
| `forge --locate` | Ochiai SBFL fault localization (filters system libs by default in v2.1) |
| `forge --gen-props PATH` | Generate Hypothesis property tests |
| `forge --bisect TEST` | Bisect a failing test back to its commit |
| `forge --flaky [N]` | Re-run tests N times to find flaky ones |
| `forge --snapshot "CMD"` / `--snapshot-check` | Capture command output as golden, diff later |
| `forge --minimize TEST INPUT` | Shrink failing inputs (ddmin, Zeller 2002) |
| `forge --add "DESC"` / `--close BUG-ID` | Log bugs in BUGS.md |
| `forge --watch` | Auto re-run on file change |
| `forge --fast` / `--fast-deep` | Run only impacted tests (1-hop / transitive Bazel-style) |
| `forge --heatmap` | Per-file failure heatmap |
| `forge --anomaly` | Flag commits with anomalous git activity |
| `forge --install-hook` / `--uninstall-hook` | Git pre-commit hook integration |

`forge --help` for the complete flag list. `forge --version` for installed version.

## How it compares to industry tools

[cycle 8 benchmark](BENCHMARK.md):

| Job | forge | Industry tool | Result |
|---|---|---|---|
| Mutation testing — `httpie/cli/argparser.py` | `--mutate` (libcst, 70 mutants) | `mutmut` (regex, 301 mutants) | **forge 100% kill in 11min** vs mutmut 33% in 16min |
| Test impact selection on cold-start | `--fast-deep` (Bazel-style transitive) | `pytest --testmon` (coverage-based) | **fast-deep wins cold-start CI** (no `.testmondata` to maintain) |
| Architecture quality metric | `--modularity` (Newman-Girvan Q) | `pydeps` (graph extraction) | **forge unique** — pydeps has no Q metric |

See [BENCHMARK.md](BENCHMARK.md) for the 6 frictions admitted.

## Scientific validation

forge has been tested through **14 pre-registered scientific cycles** on
real Python bugs from BugsInPy. Full methodology + verdicts public on
[forge-case-studies](https://github.com/sky1241/forge-case-studies).

### Production-validated capabilities

- **`forge --predict`** (Nagappan-Ball ICSE 2005, churn-only) —
  **recommended primary defect predictor**. 54-71% precision@10 holdout
  on E7-filtered scope. Beats multi-signal composite in 3 independent
  cycles (11, 13, 15).
- **`forge --carmack`** (6-signal composite) — research mode. Cycle 15
  C1 verdict OUI (Fisher p=2.5e-9 robust). Composite weights heuristic,
  not calibrated. Cycle 23 confirmed **all 6 signals are useful solo**
  (≥2x random baseline); cycle 24 benchmark of repondération NEUTRAL,
  so v2.1.0 weights kept.
- **`forge --modularity`** — Newman Q architecture metric, validated
  cycle 8 vs pydeps.
- **`forge --mutate`** — libcst AST-aware, validated cycle 8 vs mutmut
  (100% kill in 11min vs mutmut 33% in 16min on httpie).
- **`forge --gen-props` / `--minimize` / `--snapshot` / `--watch` /
  `--bisect` / `--flaky`** — validated cycle 20 v2 on 30 real cases
  (5 projects × 6 tools, 100% ratio_ok).
- **10 auxiliary tools** (`--anomaly`, `--heatmap`, `--baseline/--diff`,
  `--init/--add/--close`, `--install-hook`, `--full-cycle`,
  `--incremental-mutate`, `--flaky-dtw`) — validated cycle 21B on
  50 real cases (5 projects × 10 tools, 10/10 OUI).

### Production-ready in v2.1.0 (was research-mode in v2.0.0)

- **`forge --locate`** — `--exclude-system-libs` default ON since v2.1.0
  filters site-packages / .venv / stdlib from SBFL ranking. Pass
  `--include-system-libs` to restore v2.0.0 legacy behavior.
- **`forge --shield`** — prints `[SHIELD WARNING]` + `[SHIELD HINT]` on
  carmack short-circuit instead of silent skip. Use `--weeks-from
  <ISO_DATE_OR_SHA>` to anchor history window (fix BUG-014). Works on
  active and dormant projects when window is anchored.

### Cycles 11→24 summary

| Cycle | Hypothesis | Verdict |
|---|---|---|
| 11-15 | `forge --carmack` baseline calibrations | 1/3 OUI (cycle 15 Fisher p=2.5e-9 robust) |
| 16 v1+v2 | Cold-start AST similarity signal | REJECTED (Jaccard uniform on Python) |
| 17 | `forge --locate` at scale | REJECTED for user-facing (system files w/o filter) |
| 18 v2 | `forge --shield` on active HEAD | OUI conditional (11/11 active, 0/9 dormant) |
| 19 v2 | Composite ablation (drop kalman+wavelet) | AMBIGUOUS (populations disjoint) |
| 20 v2 | Sanity at scale, 6 main tools | OUI 6/6 on 30 real cases |
| 21A | Fix BUG-014 + locate filter + shield warning | shipped v2.1.0 |
| 21B | Sanity 10 auxiliary tools | OUI 10/10 on 50 real cases |
| 22 | incremental_mutate retest + kalman analysis | kalman vide 56% MAIS wavelet 7x discriminant |
| 23 | NO DROP — single-signal performance per algo | **6/6 signaux useful solo** (≥2x random) |
| 24 | Repondération + kalman extraction fix benchmark | NEUTRAL (delta +0.0 pts panel_ref) → v2.1.0 kept |

### Reproducibility

15+ FINAL_REPORTs publicly available with pre-registration committed
before all runs. Seeds 42/43, 44/45, 48/49, 50/51, 52/53, 54/55, 56/57
— all disjoint inter-cycles. Latest reports on
[forge-case-studies](https://github.com/sky1241/forge-case-studies)
main branch.

## What's inside

Algorithms are implemented from the papers, not wrapped from sklearn/scipy/networkx.

| Algorithm | Implementation | Reference |
|---|---|---|
| Louvain community detection | Greedy modularity gain, pure Python | Blondel et al. 2008 |
| Newman-Girvan modularity Q | `(1/2m)·Σ[A_ij − k_i·k_j/2m]·δ` | Newman & Girvan 2004 |
| Kaplan-Meier survival | Right-censoring, ties handled events-first | Kaplan & Meier 1958 |
| Adaptive Kalman filter | Innovation-based variance re-estimation | Mehra 1970 |
| Haar wavelet | Avg/diff, padded to power of 2 | Mallat 1989 |
| DTW (Dynamic Time Warping) | O(n·m) DP matrix | Sakoe & Chiba 1978 |
| Ochiai SBFL | `failed / sqrt(totalFailed × (passed+failed))` | Abreu et al. 2007 |
| ddmin | Unresolved-aware delta debugging | Zeller & Hildebrandt 2002 |
| McCabe + Halstead complexity | Cyclomatic + effort + LOC + nesting | McCabe 1976, Halstead 1977, Menzies 2007 |
| Churn-based defect prediction | `(added + deleted) / max(loc, MIN)` | Nagappan & Ball 2005 |

Validation tests pin known results: Karate Club graph Q ∈ [0.38, 0.45]
(Zachary 1977), Kaplan-Meier hand-checked survival probabilities,
two-cliques+bridge community split.

`mypy --strict` passes the entire codebase. 292 tests pass (cycle 24).

## Honest limits

- **Composite `carmack_score` weights** (kalman 0.20, wavelet 0.15,
  crash 0.20, coupling 0.15, churn 0.15, complexity 0.15) are
  **heuristic, not calibrated against a labelled dataset**. Cycle 24
  attempted performance-based repondération — NEUTRAL benchmark
  (delta +0.0 pts panel_reference). Use as ranking signal, not
  probability.
- **`forge --predict` (churn-only) outperforms `forge --carmack`
  (composite)** on Python defect prediction at this scale (3 cycles
  confirm: 11, 13, 15). Counter-intuitive but empirically robust.
- **Kalman filter on bugfix event series** is theoretically sub-optimal
  for sparse count data (Kalman gaussien assumes continuous noise).
  Hawkes process / Poisson regression would be canonical. Documented
  v2.3+ roadmap, not implemented.
- **Coverage of forge's own CLI subcommands** is partial — math
  primitives are well tested, orchestration code less so. Cycles 20
  v2 + 21B validate orchestration on real projects.

## Roadmap

- **v2.2+** : investigate Hawkes process / Poisson regression to replace
  Kalman for count data (cycle 23B finding)
- **v2.2+** : empirical cross-validation calibration of composite weights
  (instead of heuristic, after cycle 24 NEUTRAL benchmark)
- **v2.2+** : larger panel_reference (N=50+) to detect subtle signals
  noyés dans la variance N=20

## License

MIT — see [LICENSE](LICENSE). Changelog: [CHANGELOG.md](CHANGELOG.md).
Bugs: [BUGS.md](BUGS.md). Case studies:
[forge-case-studies](https://github.com/sky1241/forge-case-studies).
