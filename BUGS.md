# BUGS — forge

> Format: each bug has an ID, status, symptom, root cause, fix, and test.
> Keep this file accurate — your AI assistant (or future you) will read it before fixing bugs.

<!-- TEMPLATE
## BUG-XXX: [short description]
- **Status**: OPEN / FIXED / WONTFIX
- **Symptom**: what happens
- **Root cause**: WHY it happens (not just where)
- **Fix**: what was done (commit hash if fixed)
- **Test**: which test covers this (file:test_name)
- **Regression**: did the fix break anything else?
-->

## BUG-014: forge --shield/--carmack `--weeks N` uses system date

- **Status**: OPEN, planned v2.1
- **Date**: 2026-05-11
- **Symptom**: `forge --shield` short-circuits silently on commits older
  than `current_date - weeks`. `carmack` stage emits "No commits in last
  N weeks" then `shield` skips downstream stages (gen-props, fast-deep).
- **Root cause**: `git log --since='N weeks ago'` in
  `compute_carmack_signal()` resolves against system date, not against
  a configurable reference date. On historical commits (BugsInPy
  benchmarks) where PRE_BUG commit is 2018-2021 and system date is
  2026, `--since=4 weeks ago` returns 0 commits → cascade short-circuit.
  Also affects dormant active-repo benchmarks (e.g., thefuck last
  commit 2024-01, httpie 2024-12) where `--weeks 4` returns no activity.
- **Impact**:
  - Benchmarks on historical commits (cycles 12, 17, 18 v1) invalidated
  - Sanity tests on dormant projects show shield "doesn't work" when
    it actually does — just lacks recent activity signal
- **Fix planned**: add `--weeks-from REF_DATE` parameter to override
  system date. Refactor `carmack` + `shield` to thread reference date
  through stages. Backward-compatible: when `--weeks-from` absent,
  use system date (current behavior).
- **Workaround**:
  - Run `forge --shield --weeks 52` (or larger) on dormant projects
  - Use `forge --shield` on HEAD of active repos with recent commits
    (see cycle 18 v2 methodology)
- **Discovered**: cycle 18 v2 sub-population analysis (11/11 stages
  complete on active projects vs 0/9 on dormant).
- **Test plan v2.1**: `tests/test_forge_real_algos.py::TestWeeksFrom`
  with synthetic git history at fixed dates.
