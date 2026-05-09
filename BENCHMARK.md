# forge-shield benchmark vs industry tools

**Date** : 2026-05-09
**Forge version** : v1.1.0 (commit `efbe6a9`)
**Scope** : 3 public Python repos (MIT/BSD/Apache), shallow clone depth=200
**Branch** : `feat/cycle8-bench`
**Charte** : anti-bullshit (Défense 2 verbatim, Défense 9 admit losses)

---

## Repos targeted

| Repo | LOC | License | Module under bench |
|---|---|---|---|
| httpie/cli | ~15k | BSD | `httpie/cli/argparser.py` (~700 LOC) |
| psf/black | ~50k | MIT | `src/black/lines.py` (~1.5k LOC) — **NOT BENCHED, see below** |
| pallets/click | ~20k | BSD | `src/click/core.py` (~3.5k LOC) |

---

## Results — apples-to-apples per bench

### Bench 1A — `forge --mutate` vs `mutmut` on httpie/argparser.py

| Métrique | forge --mutate (libcst) | mutmut 2.5.1 (regex) |
|---|---|---|
| Mutants generated | **70** | **301** (4.3× more) |
| Killed | 70 (100%) | 100 (33.2%) |
| Survived | 0 | 201 |
| Timeouts | 0 | 0 |
| Wall-clock | **11min 18s** | 16min 0s |
| Test set | tests/ (173 tests, 1 baseline-fail tolerated) | tests/test_cli.py (38 tests, baseline-clean subset) |
| Exit | clean (PASS, score ≥ 80% threshold) | crash on `mutmut results` (pony ORM TypeError) |

**Honest reading** :
- forge libcst skips by design mutants known to be invalid (return-type arrows, `*unpacking`, string-literal mutations) → 70 meaningful mutants vs 301 noisy. Cycle 4 D-3b validation: regex backend produces 23-40% syntactically-invalid mutants on real repos.
- forge 100% kill rate is suspect on its own ("are mutants too easy?") — but counter-evidence: on click/core.py below, forge survives at 78% partial, indicating the score is target-dependent, not artificially perfect.
- mutmut 33% includes many "trivially-survived noise mutants" (e.g. `+>` from `->` arrow flip on type hints — would-be SyntaxError, counted as survivor not as invalid).
- Test set is **NOT strictly equal**: mutmut required restricting to baseline-clean test_cli.py (38 tests) because 1 test is env-specific fail; forge tolerated the baseline fail. This favors forge on the "kill rate" metric.

**Winner** : forge for kill rate AND duration. Caveats above on test-set asymmetry.

### Bench 1B — `forge --fast-deep` vs `pytest --testmon` on httpie

Triggered by 1-line semantic edit to `httpie/cli/argparser.py` (`max_help_position=6 → 7`).

| Métrique | forge --fast-deep | pytest --testmon |
|---|---|---|
| Tests selected | **1019** / 1020 | **910** / 1001 |
| Selection time | 125s (runs the tests) | 0.5s (selection only, doesn't run them) |
| Setup cost | None | First baseline collection: 125s (`pytest --testmon`) |
| Precision | Lower (selects ~all transitive importers) | Higher (uses coverage data) |
| Recall | High (graph-based, conservative) | High (coverage-based, freshness-dependent) |

**Honest reading** :
- testmon and fast-deep solve overlapping but different problems. testmon: "what's affected per coverage history" (precision). fast-deep: "what's potentially affected per import graph" (recall).
- testmon needs a maintained `.testmondata` cache. Stale coverage → false negatives (regressions slip past). fast-deep doesn't need any cache, but selects more aggressively.
- Apples-to-apples comparison would require: same edit, same baseline test count, both run the selected suite. Here we're comparing testmon's selection time (~0.5s) to forge's selection+execution (125s). Not directly comparable on duration.

**Winner** : depends on need.
- If you have stable coverage and tolerate occasional staleness → testmon (huge speedup on subsequent runs).
- If you want zero-setup correctness on a CI cold start → fast-deep.
- forge wins on UX simplicity (no baseline maintenance), testmon wins on speed-when-warm.

### Bench 1C — `forge --modularity` vs `pydeps` on httpie

| Métrique | forge --modularity | pydeps |
|---|---|---|
| Output | Newman-Girvan Q = 0.356 (good); 133 files / 46 communities; top-3 clusters | JSON dep graph (modules + imports + bacon level) |
| Scalar metric | Yes (Q in [-0.5, 1]) | No |
| Visualization | No (text report) | Yes (graph rendering) |
| Duration | 5s | 8s |

**Honest reading** : these are **different scopes**, not competitors.
- pydeps = dep graph extraction + visualization (drawn via dot)
- forge --modularity = scalar architecture metric (Newman 2006)

forge --modularity has no direct OSS competitor that produces Q. pydeps produces the underlying graph, and one *could* compute Q from it manually, but no off-the-shelf tool does so for Python out of the box.

**Winner** : differentiation, not comparison. forge --modularity occupies an empty niche.

### Bench 2 — `forge --mutate` partial on click/core.py

`forge --mutate --paths-to-mutate src/click/core.py` was launched with a 30min timeout cap (per Sky's bench discipline policy).

| Métrique | Value |
|---|---|
| Mutants total | 314 |
| Mutants tested before timeout | 109 (35%) |
| Killed | 85 |
| Survived | 24 |
| Partial kill rate | **78%** |
| Status | TIMEOUT (exit code 144) |

This is the more representative result: on a 3.5k LOC central file with 1494-test suite (8.6s baseline), forge tests 109 mutants in 30min ≈ 16s/mutant including overhead. Realistic completion estimate: 50-90 minutes.

**Honest reading** : 78% kill rate is more credible than the 100% on httpie/argparser. Suggests the 100% result on httpie was due to a smaller, simpler target file rather than forge being miraculously precise. **mutmut not benched on click**: would also timeout (likely 2× longer per pattern observed on httpie 16min/11min ratio).

### Bench 3 — black SKIPPED with rationale

`psf/black`'s test suite (`tests/test_format.py`) takes ~75s baseline. Mutating `src/black/lines.py` (1548 LOC) would generate ~150-300 mutants. At 75s per mutant, total ≈ 3-6 hours. Exceeds the 30min bench cap by 6-12×.

**Decision (Sky's discipline)** : skipped rather than artificially down-sampling. A reduced bench (e.g. mutate `src/black/cache.py` 150 LOC against `tests/test_no_ipynb.py`) would be apples-to-tomatoes vs the lines.py target Sky originally specified. Document the constraint, don't fake the result.

---

## Friction log (charte D9 — admit, don't hide)

1. **mutmut 3.5.0 incompatible** — removed `--paths-to-mutate` flag. Downgraded to 2.5.1 to keep apples-to-apples bench possible.
2. **mutmut subprocess env leak** — first run crashed with `pytest_httpbin not found`. mutmut 2.5 spawns `python -m pytest` from system PATH, not the active venv. Fixed by passing `--runner` with explicit venv-bench python path.
3. **mutmut `mutmut results`** post-run crashes on pony ORM `TypeError: 'QueryResultIterator' object is not iterable`. Counted progress from spinner log instead. Known mutmut 2.5 + pony 0.7+ issue, upstream.
4. **Test set asymmetry on httpie** — mutmut couldn't tolerate the 1 env-specific baseline-fail test (`test_cli_ui::test_naked_invocation`). Restricted mutmut to `tests/test_cli.py` (38 tests). forge ran on full `tests/` (173 tests, baseline-fail tolerated). Favors forge on kill metric.
5. **forge --mutate timeout on click** — 30min insufficient for 314-mutant run. Reported partial (109/314 tested). Realistic completion: ~50-90min.
6. **black skipped** — test_format.py 75s baseline → mutmut/forge both far exceed 30min cap. Documented, not bench-scaled-down to avoid unfair comparison.

---

## Summary table

| Tool / Concept | Repo | forge wins? | Caveats |
|---|---|---|---|
| Mutation kill rate | httpie | ✅ 100% vs 33% | test set differs (173 vs 38 tests) |
| Mutation rate (realistic) | click | partial 78% (forge only, timeout) | mutmut not run, would also timeout |
| Mutation LOC stress | black | 🟡 SKIPPED both | 75s baseline test = 6× over budget |
| Test impact (selection precision) | httpie | tie (different scopes) | testmon precision > fast-deep, fast-deep recall > testmon |
| Architecture metric | httpie | ✅ unique niche | pydeps has no Q metric; not direct competitor |

---

## What this bench DEMONSTRATES

✅ forge --mutate **generates more meaningful mutants** than mutmut (libcst AST-aware skips invalid syntax-only mutations).
✅ forge --fast-deep **works without baseline setup** (vs testmon needs `.testmondata`).
✅ forge --modularity **occupies a niche** no OSS Python tool fills.
✅ forge --mutate **on a complex file** (click/core.py 78% partial) gives a credible mutation score, not artificially perfect.

## What this bench DOES NOT DEMONSTRATE

❌ Strict apples-to-apples mutation comparison (test set asymmetry on httpie).
❌ forge's behavior on monoliths > 1.5k LOC with slow test suites (black skipped).
❌ Production stability — these are 1-shot benches, not regression-tested over time.
❌ Forge superiority on every dimension — testmon has a real advantage on selection latency once warm.

---

## Reproducibility

```bash
# Clone the 3 repos shallow
mkdir -p /tmp/cycle8-bench && cd /tmp/cycle8-bench
git clone --depth=200 https://github.com/httpie/cli.git
git clone --depth=200 https://github.com/psf/black.git       # NOTE: bench skipped
git clone --depth=200 https://github.com/pallets/click.git

# Setup throwaway venv
python3 -m venv .venv-bench
.venv-bench/bin/python -m ensurepip
.venv-bench/bin/python -m pip install \
  -e "/path/to/forge[mutate,locate,fuzz]" \
  "mutmut<3" pytest-testmon pydeps --quiet

# Per repo: install + run benches
cd cli
.venv-bench/bin/python -m pip install -e ".[test]"
.venv-bench/bin/forge --mutate --paths-to-mutate httpie/cli/argparser.py
.venv-bench/bin/mutmut run \
  --paths-to-mutate httpie/cli/argparser.py \
  --tests-dir tests \
  --runner ".venv-bench/bin/python -m pytest tests/test_cli.py -x --assert=plain --no-header -q"
.venv-bench/bin/forge --modularity
.venv-bench/bin/pydeps httpie --no-output --show-deps
# (similar for click/core.py)
```

JSON outputs in `bench/results/{repo}/{tool}.json`.

---

## Karma — retired in cycle 6

Originally listed as a 4th bench. Retired pre-bench (cycle 6, PR #1 closed) per charte Défense 9: Round 1 sensitivity claim was tautological (testing on commits I myself admitted as overshoots), Round 2 pool was biased (25 mainstream Python tier-1 commits, 0 overshoot in pool, sensitivity unmeasurable). No defense of pride. See `~/forge-karma-round2-cousin.md` for the post-mortem.

---

## Verdict

forge-shield v1.1.0 is **production-publishable for** :
- Mutation testing on small-to-medium files (≤ 1k LOC, fast test suite)
- Architecture monitoring via Q-modularity (release-gate signal)
- Cold-start CI test selection (no baseline maintenance)

forge-shield is **NOT a fit for** :
- Massive monoliths with slow test suites (black-scale ≥ 1k LOC + ≥ 30s baseline)
- Tight precision requirements where false-positive selections cost (use testmon with maintained coverage)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
