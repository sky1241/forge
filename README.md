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

## Honest Limits — cycle 14 case studies v5 (2026-05-11)

`forge --carmack` was tested over 5 cycles on real Python bugs from
BugsInPy. Cycle 14 (N=141 effective, stratified 40% cold-start /
60% history-rich, pre-registered seeds 48/49) tests the cold-start
re-weighting fix introduced in v1.3.0rc2.

**Verdict (pre-registered, N=141): 1/3 criteria OUI**

- **C1 OUI ✓** : Fisher exact p=0.00108 (forge 39/112 vs random 17/112)
  → forge beats random with statistical robustness (3× stronger than cycle 13's p=0.049)
- **C2 NON globally** (precision@10 = 34.5%) **BUT OUI on history-rich subset**
  (8/15 = 53.3% top10, Wilson lower ≥ 0.30)
  → forge works on its intended scope (files with ≥3 bugfix history),
    diluted on the global mixed panel by cold-start cases (15.4%)
- **C3 NON** (delta AUC calibrated vs heuristic = +0.021, below +0.05)
  → calibration finds signal direction but training set N=101 still small

### Major finding — `forge --carmack` beats `forge --predict` on holdout

| | TRAIN N=112 | **HOLDOUT N=29** |
|---|---|---|
| forge --carmack v1.3.0 (with cold-start re-weighting + complexity signal) | 34.8% | **34.5%** ✓ |
| forge --predict (churn-only) | 39.3% | 31.0% |
| random | 15.2% | 10.3% |

Reversal vs cycles 11-13. Calibrated carmack with new complexity signal +
cold-start sub-regimes A/B beats churn-only baseline on independent holdout.

### Calibration converges on coupling + complexity

| Signal | Heuristic | Calibrated (cycle 14) |
|---|---|---|
| coupling | 0.15 | **0.399** |
| complexity | 0.15 | **0.386** |
| crash | 0.20 | 0.085 |
| kalman | 0.20 | 0.033 |
| wavelet | 0.15 | 0.019 |
| churn | 0.15 | 0.078 |

Coupling + complexity = **79% of the optimal composite**. Confirms
empirically the cold-start hypothesis : files central in the import graph
+ inherently complex code = strongest predictors.

### Recommended usage

- `forge --carmack` v1.3.0 for **defect prediction on Python projects with
  bugfix history** (53% precision@10 on this scope)
- `forge --predict` for fast churn-only baseline ranking
- `forge --mutate` (libcst) for AST-aware mutation testing (validated cycle 8)
- `forge --modularity` for architecture monitoring (Newman Q)

### Cold-start signal — partial

Cold-start re-weighting (D1 fix: detection `bugfixes < 3`, sub-regimes A/B
according to coupling) reduces but does not eliminate the cold-start
blind spot. 15.4% top10 on holdout cold-start subset vs ~10% random.

Future cycle 15 will test forge on history-only panel (E7 strict) to
validate carmack's intended scope rigorously.

### Reproducibility

See [forge-case-studies](https://github.com/sky1241/forge-case-studies)
cycle14 branch for full methodology, frictions admitted, per-case
ranks, and pre-registration committed before all runs.

Earlier reports preserved for historical transparency:
- [FINAL_REPORT_v5.md](https://github.com/sky1241/forge-case-studies/blob/main/FINAL_REPORT_v5.md) (cycle 14 v5, 1/3 OUI, N=141)
- [FINAL_REPORT_v4.md](https://github.com/sky1241/forge-case-studies/blob/main/FINAL_REPORT_v4.md) (cycle 13 v4, 1/3 OUI, E7 filter)
- [FINAL_REPORT_v3.md](https://github.com/sky1241/forge-case-studies/blob/main/FINAL_REPORT_v3.md) (cycle 12 v3, 0/3 OUI, no E7)
- [FINAL_REPORT.md](https://github.com/sky1241/forge-case-studies/blob/main/FINAL_REPORT.md) (cycle 11 v2, 1/3 OUI, N=15)
- v1 INVALID (cycle 11 v1, REVERT commit `0b55e2a`)

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
