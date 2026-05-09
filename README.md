# forge

[![Tests](https://github.com/sky1241/forge/actions/workflows/test.yml/badge.svg)](https://github.com/sky1241/forge/actions/workflows/test.yml)
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/sky1241/forge)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Pytest regression shield with predictive analytics for Python repos. Single-file core, stdlib-only runtime (pytest is the only required dep — bring your own).

```bash
pip install forge-shield
forge --init    # scaffold .forge/ and BUGS.md
forge --baseline # snapshot current test suite
forge           # detect regressions vs baseline
forge --carmack # rank files by predicted defect risk
```

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
