# forge

[![Tests](https://github.com/sky1241/forge/actions/workflows/test.yml/badge.svg)](https://github.com/sky1241/forge/actions/workflows/test.yml)
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/sky1241/forge)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/forge-shield)](https://pypi.org/project/forge-shield/)

**A pytest regression shield with predictive analytics — validated across 14 pre-registered scientific cycles on real Python bugs.**

Single-file core. Stdlib-only runtime. Algorithms implemented from the papers, not wrapped from sklearn / scipy.

```bash
pip install forge-shield
forge --init && forge --baseline    # 30 seconds to bootstrap
forge --predict                     # rank files by defect risk
```

---

## Why forge?

Most defect prediction and test orchestration tools either:
- wrap sklearn / networkx in a black box, or
- make claims without empirical validation, or
- require complex setup before you see value.

**forge does the opposite:**

- **Empirically validated** on real bugs from [BugsInPy](https://github.com/soarsmu/BugsInPy) — pre-registered hypotheses, public verdicts, a few losses honestly admitted
- **Algorithms from the papers** — Louvain, Kaplan-Meier, Newman Q, Ochiai, Halstead, McCabe, Wavelet, Kalman, DTW, ddmin, churn — full citations below
- **Zero runtime deps** beyond pytest (your test runner). No `.venv` bloat, no transitive supply chain
- **One file** — `forge.py`, mypy `--strict` clean, **292 tests passing** on Linux / macOS / Windows × Python 3.11 / 3.12 / 3.13

---

## Headline finding

Across 3 independent pre-registered cycles on real Python bugs:

| Predictor | precision@10 (holdout) |
|---|---|
| `forge --predict` (churn-only, Nagappan-Ball 2005) | **54 – 71 %** |
| `forge --carmack` (6-signal composite) | 28 – 45 % |
| random baseline | ~ 9 % |

**The simple churn-only baseline beats the sophisticated multi-signal composite.** Counter-intuitive, but empirically robust over 3 independent cycles. We document this honestly rather than ship marketing claims.

---

## 60-second tour

```bash
# Install + bootstrap in your repo
pip install forge-shield
cd your-python-project
forge --init                       # creates .forge/ + BUGS.md
forge --baseline                   # snapshots current test suite

# Now make changes. Then any of:
forge                              # detect regressions vs baseline
forge --predict                    # rank files by defect risk
forge --fast                       # run only tests impacted by recent changes
forge --mutate                     # how good are my tests? (AST-aware mutation)
forge --bisect TEST_NAME           # find the commit that broke TEST_NAME
forge --flaky 5                    # run tests 5× to detect unstable ones
forge --shield                     # orchestrated pipeline: predict → gen-tests → run impacted
```

**Real `forge --predict` output** (sample shape):

```
==================================================
  DEFECT PREDICTION — 1245 files, last 8 weeks
==================================================

  RANK  RISK   FILE
   1    0.94   httpie/cli/argparser.py    (churn 0.41, age 3w, 12 authors)
   2    0.83   httpie/output/formatters/colors.py
   3    0.71   httpie/cli/items.py
   ...
```

---

## Install variants

| Command | What you get |
|---|---|
| `pip install forge-shield` | Core (stdlib + pytest only) |
| `pip install 'forge-shield[mutate]'` | `+ --mutate` (libcst AST-aware) |
| `pip install 'forge-shield[locate]'` | `+ --locate` (coverage.py) |
| `pip install 'forge-shield[fuzz]'` | `+ --gen-props` (Hypothesis) |
| `pip install 'forge-shield[all]'` | Everything |

**Requirements:** Python ≥ 3.11. Cross-platform: macOS / Linux / Windows (CI tested across 9 OS × Python combinations).

---

## Sub-commands

### Prediction & analysis
| Command | What it does |
|---|---|
| `forge --predict` | **Recommended primary predictor.** Rank files by churn-based defect risk (Nagappan-Ball 2005) |
| `forge --carmack` | Multi-signal risk score (research mode, 6 signals composite) |
| `forge --carmack --weeks-from <ISO_OR_SHA>` | Anchor history window to a date (BUG-014 fix) |
| `forge --modularity` | Newman-Girvan Q over the import graph |
| `forge --anomaly` | Flag commits with anomalous git activity |
| `forge --heatmap` | Per-file failure heatmap |

### Test orchestration
| Command | What it does |
|---|---|
| `forge` | Run tests vs baseline (detect regressions) |
| `forge --baseline` | Snapshot the suite |
| `forge --fast` / `--fast-deep` | Run only impacted tests (1-hop / transitive, Bazel-style) |
| `forge --bisect TEST` | Bisect a failing test back to its commit |
| `forge --flaky [N]` | Re-run tests N times to find flaky ones |
| `forge --watch` | Auto re-run on file change |
| `forge --shield` | Orchestrate `predict → gen-props → fast-deep` |

### Test quality & generation
| Command | What it does |
|---|---|
| `forge --mutate [--paths-to-mutate FILE]` | Mutation testing (libcst AST-aware) |
| `forge --mutate --incremental-mutate --since SHA` | Mutate only files changed since SHA |
| `forge --locate` | Ochiai SBFL fault localization (filters system libs by default) |
| `forge --gen-props PATH` | Generate Hypothesis property tests |
| `forge --minimize TEST INPUT` | Shrink failing inputs (ddmin, Zeller 2002) |
| `forge --snapshot "CMD"` / `--snapshot-check` | Capture command output as golden, diff later |

### Project ops
| Command | What it does |
|---|---|
| `forge --init` | Scaffold `.forge/` + `BUGS.md` |
| `forge --add "DESC"` / `--close BUG-ID` | Log bugs in BUGS.md |
| `forge --install-hook` / `--uninstall-hook` | Git pre-commit hook integration |

Run `forge --help` for the complete flag list. `forge --version` for installed version.

---

## How forge compares to industry tools

From [cycle 8 external benchmark](BENCHMARK.md):

| Job | forge | Industry tool | Result |
|---|---|---|---|
| Mutation testing (httpie/cli/argparser.py) | `--mutate` libcst, 70 mutants | `mutmut` regex, 301 mutants | **forge: 100 % kill in 11 min** vs mutmut 33 % in 16 min |
| Test impact selection on cold-start CI | `--fast-deep` (Bazel-style transitive) | `pytest --testmon` (coverage-based) | **forge wins cold-start** (no `.testmondata` to maintain) |
| Architecture quality metric | `--modularity` (Newman-Girvan Q) | `pydeps` (graph extraction only) | **forge unique** — pydeps has no Q metric |

See [BENCHMARK.md](BENCHMARK.md) for the 6 frictions admitted.

---

## Scientific validation

forge has been tested through **14 pre-registered scientific cycles** on real Python bugs from BugsInPy. Full methodology + verdicts public on [forge-case-studies](https://github.com/sky1241/forge-case-studies).

### What "pre-registered" means

Before each cycle:
1. Hypothesis written and committed to GitHub
2. Eligibility criteria for the test panel locked
3. Train / test seeds fixed (disjoint inter-cycles)
4. Pass / fail thresholds set in stone

After the cycle: results published verbatim. No threshold shift, no cherry-pick, no post-hoc justification.

This is standard in clinical research and ML publication. Rare in OSS dev tools.

### Production-validated capabilities

| Tool | Validation source |
|---|---|
| `forge --predict` | **54 – 71 % precision@10** holdout (cycles 11, 13, 15) — recommended primary predictor |
| `forge --carmack` | Cycle 15 C1 verdict: Fisher exact `p = 2.5e-9` (forge 47/105 vs random 9/105) |
| `forge --modularity` | Cycle 8 benchmark vs pydeps (unique Newman Q metric in OSS Python) |
| `forge --mutate` | Cycle 8 benchmark vs mutmut: 100 % kill rate in 11 min |
| `forge --gen-props`, `--minimize`, `--snapshot`, `--watch`, `--bisect`, `--flaky` | Cycle 20 v2: 30 real cases, 5 projects, 100 % pass |
| 10 auxiliary tools (`--anomaly`, `--heatmap`, `--baseline`/`--diff`, `--init`/`--add`/`--close`, `--install-hook`, `--full-cycle`, `--incremental-mutate`, `--flaky-dtw`) | Cycle 21B: 50 real cases, 5 projects, 10 / 10 pass |

### Cycles 11 → 24 summary

| Cycle | Hypothesis tested | Verdict |
|---|---|---|
| 11 – 15 | `--carmack` composite calibration | 1/3 OUI (cycle 15 Fisher `p = 2.5e-9` robust) |
| 16 | Cold-start AST similarity signal | REJECTED (Jaccard uniform on Python) |
| 17 | `--locate` at scale | REJECTED for user-facing (system files w/o filter) |
| 18 v2 | `--shield` on active HEAD | OUI conditional (11 / 11 active, 0 / 9 dormant) |
| 19 v2 | Composite ablation (drop kalman + wavelet) | AMBIGUOUS (populations partially disjoint) |
| 20 v2 | Sanity at scale, 6 main tools | OUI 6 / 6 on 30 real cases |
| 21A | Fix BUG-014 + locate filter + shield warning | shipped v2.1.0 |
| 21B | Sanity 10 auxiliary tools | OUI 10 / 10 on 50 real cases |
| 22 | incremental-mutate retest + kalman analysis | kalman 56 % zeros; wavelet 7 × discriminant |
| 23 | NO DROP — single-signal performance per algo | 6 / 6 signals useful solo (≥ 2 × random) |
| 24 | Repondération + kalman extraction fix benchmark | NEUTRAL (∆ + 0.0 on panel_ref) → v2.1.0 kept |

### Reproducibility

**15+ FINAL_REPORTs** publicly available with pre-registration committed before all runs. Seeds 42/43, 44/45, 48/49, 50/51, 52/53, 54/55, 56/57 — all disjoint inter-cycles. Anyone can `git clone forge-case-studies && bash run_all.sh`.

---

## Algorithms (papers, not wrappers)

| Algorithm | Implementation | Reference |
|---|---|---|
| Louvain community detection | Greedy modularity gain, pure Python | Blondel et al. 2008 |
| Newman-Girvan modularity Q | `(1/2m)·Σ[A_ij − k_i·k_j/2m]·δ` | Newman & Girvan 2004 |
| Kaplan-Meier survival | Right-censoring, ties handled events-first | Kaplan & Meier 1958 |
| Adaptive Kalman filter | Innovation-based variance re-estimation | Mehra 1970 |
| Haar wavelet | Avg / diff, padded to power of 2 | Mallat 1989 |
| DTW (Dynamic Time Warping) | O(n·m) DP matrix | Sakoe & Chiba 1978 |
| Ochiai SBFL | `failed / sqrt(totalFailed × (passed + failed))` | Abreu et al. 2007 |
| ddmin (delta debugging) | Unresolved-aware shrinking | Zeller & Hildebrandt 2002 |
| McCabe + Halstead complexity | Cyclomatic + effort + LOC + nesting | McCabe 1976, Halstead 1977, Menzies 2007 |
| Churn-based defect prediction | `(added + deleted) / max(loc, MIN)` | Nagappan & Ball 2005 |

Validation tests pin known results: Karate Club graph Q ∈ [0.38, 0.45] (Zachary 1977), Kaplan-Meier hand-checked survival probabilities, two-cliques + bridge community split detection.

`mypy --strict` passes the entire codebase. **292 tests pass** (cycle 24 state).

---

## Honest limits

- **`forge --carmack` composite weights** are heuristic, not calibrated against a labelled dataset. Cycle 24 attempted performance-based repondération — NEUTRAL benchmark on `panel_reference`. Use as a ranking signal, not a probability.
- **`forge --predict` (churn-only) outperforms `forge --carmack`** on Python defect prediction at this scale (3 independent cycles confirm). Counter-intuitive but empirically robust.
- **Kalman filter on bugfix event series** is theoretically sub-optimal for sparse count data (Kalman assumes continuous Gaussian noise). Hawkes process / Poisson regression would be canonical. Documented in v2.3+ roadmap.
- **Coverage of forge's own CLI orchestration code** is partial — math primitives are well tested, orchestration code less so. Cycles 20 v2 + 21B validate orchestration on real projects.

---

## Roadmap

- **v2.2+** : investigate Hawkes process / Poisson regression to replace Kalman for count data (cycle 23B finding)
- **v2.2+** : empirical cross-validation calibration of composite weights (after cycle 24 NEUTRAL)
- **v2.2+** : larger `panel_reference` (N = 50+) to detect subtle signals masked by N = 20 variance

---

## Links

- [CHANGELOG.md](CHANGELOG.md) — version history
- [BUGS.md](BUGS.md) — open issue tracker
- [BENCHMARK.md](BENCHMARK.md) — cycle 8 vs industry tools
- [forge-case-studies](https://github.com/sky1241/forge-case-studies) — 15+ FINAL_REPORTs with pre-registration

MIT License — see [LICENSE](LICENSE).
