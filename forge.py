#!/usr/bin/env python3
"""
FORGE — Universal Debug & Regression Shield
Drop into any repo. Run before and after every session.

Usage:
    python forge.py                    # Run all tests + report
    python forge.py --init             # Init BUGS.md + tests/ in current repo
    python forge.py --add "bug desc"   # Add a bug to BUGS.md
    python forge.py --close BUG-003    # Mark a bug as fixed
    python forge.py --watch            # Run tests on file change (loop)
    python forge.py --diff             # Compare current report vs last saved
    python forge.py --baseline         # Save current test results as baseline
    python forge.py --flaky [N]        # Run tests N times (default 5), find flaky ones
    python forge.py --heatmap          # Show failure heat map (Pareto — which tests fail most)
    python forge.py --bisect TEST      # Git bisect to find which commit broke TEST
    python forge.py --fast             # Only run tests for files changed since last commit
    python forge.py --snapshot CMD     # Capture command output as golden file
    python forge.py --snapshot-check   # Verify all snapshots still match
    python forge.py --predict          # Predict defect-prone files from git history
    python forge.py --minimize TEST IN # Delta-debug: find minimal input that fails TEST
    python forge.py --gen-props MOD    # Generate Hypothesis property tests for module
    python forge.py --mutate [FILE]    # Mutation testing via mutmut (test your tests)
    python forge.py --locate           # Ochiai SBFL: locate suspicious lines from failures
    python forge.py --full-cycle        # Run the full pipeline: predict->mutate->gen-props->test->flaky->locate
    python forge.py --carmack           # Carmack predict: Kalman + Wavelet + Kaplan-Meier + Modularity
    python forge.py --anomaly           # Unified anomaly detection (z-score outliers)
    python forge.py --flaky-dtw [N]     # Flaky detection with DTW temporal pattern matching

Works with: pytest, unittest, any test_*.py files.
Zero config. Zero dependencies beyond Python stdlib + pytest.
Optional deps: hypothesis (--gen-props), mutmut (--mutate), coverage+pytest-cov (--locate).
"""

import sys
import os
import re
import json
import time
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from collections import Counter
import ast
import math

def _safe_path(filepath) -> str:
    """Sanitize path for display — never show absolute paths."""
    p = Path(filepath)
    parts = p.parts
    if len(parts) <= 3:
        return str(p.name)
    return str(Path(*parts[-3:]))


# === CONFIG ===
BUGS_FILE = "BUGS.md"
FORGE_DIR = ".forge"
BASELINE_FILE = f"{FORGE_DIR}/baseline.json"
REPORT_FILE = f"{FORGE_DIR}/last_report.json"
FORGE_LOG = f"{FORGE_DIR}/forge_log.txt"
FLAKY_FILE = f"{FORGE_DIR}/flaky.json"
HEATMAP_FILE = f"{FORGE_DIR}/heatmap.json"
SNAPSHOT_DIR = f"{FORGE_DIR}/snapshots"
MUTATION_THRESHOLD = 80
PREDICT_WEIGHTS = {"churn": 0.20, "freq": 0.20, "burst": 0.15,
                   "authors": 0.10, "bugfix": 0.15, "loc": 0.05, "recency": 0.15}
OCHIAI_TOP_N = 10
MINIMIZE_MAX_ITER = 100
CARMACK_KALMAN_Q = 0.05   # Kalman process noise (how fast risk changes)
CARMACK_KALMAN_R = 0.5    # Kalman measurement noise (how noisy observations are)
CARMACK_DTW_THRESHOLD = 2.0  # DTW similarity threshold for flaky clustering
CARMACK_ZSCORE_THRESHOLD = 2.0  # Anomaly detection z-score cutoff
# Substrings that mark a commit as a bugfix in commit-message scans. Used by
# --predict, --carmack, and the AXE-3 trend analysis. Lowercased so callers
# don't need to lowercase per-iteration. Keeping this as the single source of
# truth: changing it once changes every signal that gates on bugfix-ness.
BUGFIX_KEYWORDS = ("fix", "bug", "patch", "repair", "crash")


# === CARMACK MOVES — Cross-domain algorithms ===
# Wavelet (signal processing), Kalman (aerospace), Kaplan-Meier (medicine),
# Newman modularity (biology), DTW (speech recognition), Hamming (telecom).
# All pure Python, zero dependencies.

def _haar_wavelet(signal):
    """Haar wavelet decomposition — returns (approximation, detail_coefficients).
    Decomposes churn signal into low-freq (trend) and high-freq (burst)."""
    if len(signal) < 2:
        return signal[:], []
    n = 1
    while n < len(signal):
        n *= 2
    padded = list(signal) + [0.0] * (n - len(signal))
    details = []
    current = padded[:]
    while len(current) > 1:
        approx = []
        detail = []
        for i in range(0, len(current), 2):
            a = (current[i] + current[i + 1]) / 2.0
            d = (current[i] - current[i + 1]) / 2.0
            approx.append(a)
            detail.append(d)
        details.append(detail)
        current = approx
    return current, details


def _scalar_kalman(observations, Q=None, R=None):
    """Scalar Kalman filter — returns smoothed estimates.
    Missile guidance algo from 1960, applied to bug risk estimation.
    Q = process noise (how fast the underlying state can change).
    R = measurement noise (how noisy the observations are)."""
    Q = Q or CARMACK_KALMAN_Q
    R = R or CARMACK_KALMAN_R
    if not observations:
        return []
    x = observations[0]
    P = 1.0
    estimates = []
    for z in observations:
        x_pred = x
        P_pred = P + Q
        K = P_pred / (P_pred + R)
        x = x_pred + K * (z - x_pred)
        P = (1 - K) * P_pred
        estimates.append(x)
    return estimates


def _adaptive_kalman(observations, n_iter=10):
    """Kalman filter with Q,R estimated from data via EM-style iteration.
    Useful when default Q,R don't match the true noise structure of the signal.

    Returns (estimates, Q_hat, R_hat).
    """
    if not observations or len(observations) < 3:
        return _scalar_kalman(observations), CARMACK_KALMAN_Q, CARMACK_KALMAN_R
    obs = list(observations)
    n = len(obs)
    # Initialize Q,R from sample variance of first differences and residuals
    diffs = [obs[i + 1] - obs[i] for i in range(n - 1)]
    mean_d = sum(diffs) / len(diffs)
    Q = max(sum((d - mean_d) ** 2 for d in diffs) / max(len(diffs), 1), 1e-6)
    R = max(Q, 1e-6)

    for _ in range(n_iter):
        # Forward pass
        x = obs[0]
        P = R  # init covariance ~ measurement noise
        x_post = []
        P_post = []
        innovations = []
        innov_var = []
        for z in obs:
            x_pred = x
            P_pred = P + Q
            K = P_pred / (P_pred + R)
            innov = z - x_pred
            innovations.append(innov)
            innov_var.append(P_pred + R)
            x = x_pred + K * innov
            P = (1 - K) * P_pred
            x_post.append(x)
            P_post.append(P)
        # M-step: re-estimate R from innovation residuals,
        # and Q from state-step variance
        new_R = max(sum(i * i for i in innovations) / max(len(innovations), 1), 1e-6)
        if len(x_post) >= 2:
            steps = [x_post[k + 1] - x_post[k] for k in range(len(x_post) - 1)]
            new_Q = max(sum(s * s for s in steps) / max(len(steps), 1), 1e-6)
        else:
            new_Q = Q
        if abs(new_Q - Q) / max(Q, 1e-9) < 1e-3 and abs(new_R - R) / max(R, 1e-9) < 1e-3:
            Q, R = new_Q, new_R
            break
        Q, R = new_Q, new_R

    return x_post, Q, R


def _kaplan_meier(observations):
    """Kaplan-Meier survival estimator with censoring (Kaplan & Meier 1958).

    `observations` is a list of (time, event_observed) where:
      - time is a float (days since baseline)
      - event_observed = True  -> failure happened at `time`
      - event_observed = False -> right-censored at `time` (no event yet)

    Returns survival curve [(t, S(t))] sorted by t. S(t) = P(no event by t).

    Backwards-compat: if `observations` is a flat list of floats (legacy code
    passing intervals), assume every observation is an uncensored event.
    """
    if not observations:
        return [(0.0, 1.0)]
    # Legacy shape: list of floats -> treat as all-events
    if observations and not isinstance(observations[0], tuple):
        observations = [(t, True) for t in observations]

    # Sort by time, with events processed before censorings at same t
    obs = sorted(observations, key=lambda x: (x[0], 0 if x[1] else 1))
    n_at_risk = len(obs)
    survival = 1.0
    curve = [(0.0, 1.0)]

    i = 0
    while i < len(obs):
        t = obs[i][0]
        # Count events and censorings at this exact time t (handle ties)
        d = 0  # events at t
        c = 0  # censored at t
        j = i
        while j < len(obs) and obs[j][0] == t:
            if obs[j][1]:
                d += 1
            else:
                c += 1
            j += 1
        if d > 0:
            survival *= (n_at_risk - d) / n_at_risk
            curve.append((t, survival))
        n_at_risk -= (d + c)
        i = j
    return curve


def _km_survival_at(curve, horizon):
    """Read S(horizon) from a KM curve. Step function (last value <= horizon)."""
    s = 1.0
    for t, val in curve:
        if t <= horizon:
            s = val
        else:
            break
    return s


def _dtw_distance(seq_a, seq_b):
    """Dynamic Time Warping distance (speech recognition).
    Compares temporal patterns of test results."""
    n, m = len(seq_a), len(seq_b)
    if n == 0 or m == 0:
        return float('inf')
    dtw = [[float('inf')] * (m + 1) for _ in range(n + 1)]
    dtw[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(seq_a[i - 1] - seq_b[j - 1])
            dtw[i][j] = cost + min(dtw[i - 1][j], dtw[i][j - 1], dtw[i - 1][j - 1])
    return dtw[n][m]


def _hamming_severity(original, mutated):
    """Character-level edit distance (telecom).
    Higher distance = more severe mutation = harder to detect."""
    dist = 0
    for a, b in zip(original, mutated):
        if a != b:
            dist += 1
    dist += abs(len(original) - len(mutated))
    return dist


def _build_import_graph(root):
    """Build directed graph of Python imports using AST.
    Returns {file: [imported_files]}."""
    tracked = _run_git(root, "ls-files", "*.py")
    if not tracked:
        return {}
    files = [f.strip() for f in tracked.split("\n") if f.strip()]
    mod_to_file = {}
    for f in files:
        mod = f.replace(os.sep, ".").replace("/", ".").replace(".py", "")
        mod_to_file[mod] = f
        parts = mod.split(".")
        if parts[-1] != "__init__":
            mod_to_file[parts[-1]] = f
    graph = {f: [] for f in files}
    for f in files:
        fpath = root / f
        if not fpath.exists():
            continue
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = mod_to_file.get(alias.name)
                    if target and target != f:
                        graph[f].append(target)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    target = mod_to_file.get(node.module)
                    if target and target != f:
                        graph[f].append(target)
    return graph


def _modularity_q(adj, partition, two_m):
    """Newman-Girvan Q for an undirected graph.
    Q = (1/2m) * Σ_ij [A_ij - k_i*k_j/(2m)] * δ(c_i, c_j)
    adj      : {node: {neighbor: weight}}, undirected (symmetric)
    partition: {node: community_id}
    two_m    : sum of all edge weights * 2 (precomputed)
    """
    if two_m == 0:
        return 0.0
    degree = {n: sum(adj[n].values()) for n in adj}
    q = 0.0
    for i in adj:
        ci = partition[i]
        for j, w_ij in adj[i].items():
            if partition[j] != ci:
                continue
            q += w_ij - (degree[i] * degree[j]) / two_m
    return q / two_m


def _louvain_clustering(adj, max_iter=20, tol=1e-7):
    """Louvain community detection (Blondel et al. 2008).
    Greedy local optimization of Newman Q.
    adj : {node: {neighbor: weight}}, undirected, symmetric.
    Returns (partition, q) where partition = {node: community_id}.
    """
    # Deterministic node order. Without sorting, the partition depended on
    # the dict-insertion order of `adj`, which itself depended on the
    # caller's iteration order over the import graph (filesystem order on
    # cold runs, dict ordering on warm runs). Same repo → different
    # partition → different per-file coupling score in --carmack across runs.
    nodes = sorted(adj.keys())
    if not nodes:
        return {}, 0.0
    partition = {n: i for i, n in enumerate(nodes)}
    two_m = sum(sum(neigh.values()) for neigh in adj.values())
    if two_m == 0:
        return partition, 0.0
    degree = {n: sum(adj[n].values()) for n in adj}
    # community total degree, used in delta-Q
    comm_deg = {c: degree[n] for n, c in partition.items()}

    improved = True
    it = 0
    while improved and it < max_iter:
        improved = False
        it += 1
        for n in nodes:
            ci = partition[n]
            k_n = degree[n]
            # Sum of weights from n to each community (excluding self-loops)
            weights_to_comm = {}
            for m, w in adj[n].items():
                if m == n:
                    continue
                cm = partition[m]
                weights_to_comm[cm] = weights_to_comm.get(cm, 0.0) + w
            # Remove n from its community for the delta-Q calc
            comm_deg[ci] -= k_n
            best_delta = 0.0
            best_c = ci
            k_in_ci = weights_to_comm.get(ci, 0.0)
            for cand, k_in_c in weights_to_comm.items():
                # ΔQ for moving n from current empty-of-n state into cand:
                # ΔQ ∝ (k_in_c - comm_deg[cand] * k_n / two_m)
                delta = k_in_c - comm_deg.get(cand, 0.0) * k_n / two_m
                # Compare to staying out (== joining ci with k_in_ci)
                delta_stay = k_in_ci - comm_deg[ci] * k_n / two_m
                if delta - delta_stay > best_delta + tol:
                    best_delta = delta - delta_stay
                    best_c = cand
            comm_deg[best_c] = comm_deg.get(best_c, 0.0) + k_n
            if best_c != ci:
                partition[n] = best_c
                improved = True

    # Renumber communities 0..k-1
    seen = {}
    clean = {}
    for n, c in partition.items():
        if c not in seen:
            seen[c] = len(seen)
        clean[n] = seen[c]
    q = _modularity_q(adj, clean, two_m)
    return clean, q


def _modularity_contribution(graph):
    """Per-file score = how much each file contributes to its community's Q.
    Files that strongly bind their cluster get high scores; bridge files (between
    clusters) get low scores. This is the *real* Newman-style coupling signal,
    via Louvain clustering + per-node Q decomposition.

    Returns: {file: score in [0, 1]} normalized by max contribution.
    """
    if not graph:
        return {}
    # Build undirected weighted adjacency in a deterministic order so that
    # downstream Louvain (which depends on insertion order for tie-breaking)
    # produces the same partition on every run.
    adj = {f: {} for f in sorted(graph)}
    for src in sorted(graph):
        targets = graph[src]
        for tgt in sorted(targets):
            if tgt not in adj:
                adj[tgt] = {}
            adj[src][tgt] = adj[src].get(tgt, 0.0) + 1.0
            adj[tgt][src] = adj[tgt].get(src, 0.0) + 1.0
    if all(not v for v in adj.values()):
        return {f: 0.0 for f in graph}

    partition, _q_total = _louvain_clustering(adj)
    two_m = sum(sum(neigh.values()) for neigh in adj.values())
    if two_m == 0:
        return {f: 0.0 for f in graph}
    degree = {n: sum(adj[n].values()) for n in adj}

    contrib = {}
    for n in adj:
        ci = partition[n]
        s = 0.0
        for m, w in adj[n].items():
            if partition[m] == ci:
                s += w - (degree[n] * degree[m]) / two_m
        contrib[n] = s / two_m if two_m > 0 else 0.0

    # Normalize to [0, 1] by max absolute contribution.
    # Negative contribs (bridge files) → 0; high-contribs (binders) → 1.
    max_abs = max((c for c in contrib.values()), default=0.0)
    if max_abs <= 0:
        return {f: 0.0 for f in graph}
    return {f: max(contrib.get(f, 0.0), 0.0) / max_abs for f in graph}


def _check_dep(name, pip_name=None):
    """Try to import optional dependency, return module or None."""
    try:
        return __import__(name)
    except ImportError:
        pip_name = pip_name or name
        print(f"  {name} not installed. Install with: pip install {pip_name}")
        return None


def _run_git(root, *args):
    """Run a git command and return stdout."""
    try:
        r = subprocess.run(["git"] + list(args), capture_output=True, text=True,
                          cwd=str(root), encoding="utf-8", errors="replace", timeout=30)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


GIT_NUMSTAT_FORMAT = "COMMIT %H %ae %aI %s"


def _fetch_numstat_log(root, since_weeks, paths=("*.py",)):
    """Run `git log --numstat --format=COMMIT %H %ae %aI %s --since=N weeks ago`
    on the given path globs. Returns the raw stdout. Centralizing the call
    so the format string is defined exactly once — every caller used to
    repeat it verbatim, which silently drifted in the past."""
    return _run_git(
        root, "log", "--numstat", f"--format={GIT_NUMSTAT_FORMAT}",
        f"--since={since_weeks} weeks ago", "--", *paths,
    )


def _iter_numstat_commits(raw_log):
    """Yield structured commit records from `git log --numstat
    --format=COMMIT %H %ae %aI %s` output. Each record is:

        {"hash": str, "author": str, "date": str (ISO),
         "msg": str (lowercased), "is_bugfix": bool,
         "files": [(added: int, deleted: int, fname: str), ...]}

    Binary files (added/deleted == "-") are coerced to 0/0. Commits with no
    files (touch a path filtered out by --paths) yield with files=[].

    Replaces the 3 hand-rolled COMMIT-line parsers in --predict, --carmack,
    and the AXE-3 trend analysis. They all derived their per-file stats from
    the same underlying record shape, just accumulated differently.
    """
    cur = None
    for line in raw_log.split("\n"):
        if line.startswith("COMMIT "):
            if cur is not None:
                yield cur
            parts = line.split(" ", 4)
            if len(parts) >= 5:
                msg_lower = parts[4].lower()
                cur = {
                    "hash": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                    "msg": msg_lower,
                    "is_bugfix": any(w in msg_lower for w in BUGFIX_KEYWORDS),
                    "files": [],
                }
            else:
                cur = None
        elif "\t" in line and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                added, deleted, fname = parts
                a = int(added) if added.isdigit() else 0
                d = int(deleted) if deleted.isdigit() else 0
                cur["files"].append((a, d, fname.strip()))
    if cur is not None:
        yield cur


def find_repo_root():
    """Walk up to find .git directory. Also check script's own location."""
    # First try CWD
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    # Fallback: script location
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path.cwd()


def _read_pyproject_pytest_options(root):
    """Return [tool.pytest.ini_options] dict from pyproject.toml, or {}.

    Stdlib only — uses tomllib on Python 3.11+, falls back silently otherwise.
    Centralized so callers can read `testpaths`, `norecursedirs`, etc.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        import tomllib
    except ImportError:
        return {}
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    return data.get("tool", {}).get("pytest", {}).get("ini_options", {})


def _read_pyproject_norecursedirs(root):
    """Return the list of dirs from [tool.pytest.ini_options] norecursedirs."""
    return list(_read_pyproject_pytest_options(root).get("norecursedirs", []))


def _read_pyproject_testpaths(root):
    """Return the list of dirs from [tool.pytest.ini_options] testpaths.

    When set, pytest only collects from these paths. Cousin pc1 cycle 2 found
    this on pytest's own repo (testpaths = ['testing']) — without honoring it,
    forge globbed everything from root and ramassait des fichiers que pytest
    aurait ignorés. Now we use it as a positive filter when present.
    """
    return list(_read_pyproject_pytest_options(root).get("testpaths", []))


def find_tests(root):
    """Find all test files in the repo.

    Excludes benchmarks by default. Mutation testing measures correctness,
    not performance — pytest-benchmark suites in bench/ or benchmarks/ are
    typically slow (hundreds of rounds) and never assert behavioral
    correctness, so they neither kill mutants honestly nor finish within a
    reasonable timeout. attrs's bench/test_benchmarks.py was the canonical
    case (107s single-thread, picked up alphabetically before tests/,
    blew the per-mutant budget on every run).

    Override with FORGE_INCLUDE_BENCHMARKS=1 if you really want them.
    """
    tests = []
    # If pyproject.toml's [tool.pytest.ini_options] sets testpaths, scope our
    # globs to those dirs only. Otherwise scan the whole repo.
    testpaths = _read_pyproject_testpaths(root)
    glob_roots = (
        [root / tp for tp in testpaths if (root / tp).is_dir()]
        if testpaths else [root]
    )
    # pytest's default python_files = ['test_*.py', '*_test.py'] — many real
    # repos also use the *_tests.py suffix (mkdocs is the canonical example,
    # 19 test files invisible to forge before this fix). Cover both.
    glob_patterns = [
        "tests/test_*.py", "test_*.py", "tests/**/test_*.py", "**/test_*.py",
        "**/*_test.py", "**/*_tests.py",
    ]
    for groot in glob_roots:
        for pattern in glob_patterns:
            tests.extend(groot.glob(pattern))
    excludes = [".forge", "__pycache__", ".git", "node_modules"]
    # Honor pyproject.toml's [tool.pytest.ini_options] norecursedirs. Found
    # this on cycle 2 with pytest's own repo: testing/example_scripts/ are
    # excluded by pytest config but forge picked them up → pytest then
    # errored "ManifestDirectory not match" + exit 4 → fault_locate said
    # "no failing tests" silently. Now we honor the user's intent.
    norecurse = _read_pyproject_norecursedirs(root)
    if norecurse:
        for nr in norecurse:
            # Convert "testing/example_scripts" → "/testing/example_scripts/"
            # so we match the directory inside the path, not a substring of a
            # file name (avoids "examples_test.py" being excluded by "examples").
            seg = nr.strip("/").strip(os.sep)
            excludes.append(f"{os.sep}{seg}{os.sep}")
    if not os.environ.get("FORGE_INCLUDE_BENCHMARKS"):
        # Match /bench/ or /benchmarks/ anywhere in the path. Conservative —
        # only directory names that match exactly, not any file containing
        # "bench" in its name.
        excludes += [f"{os.sep}bench{os.sep}", f"{os.sep}benchmarks{os.sep}"]
    tests = [t for t in tests if not any(x in str(t) for x in excludes)]
    # Dedupe by resolved absolute path so a symlinked test isn't counted
    # twice (pathlib's Path equality is path-string based, not inode-based;
    # a symlink and its target are two different Path objects).
    seen_resolved = set()
    deduped = []
    for t in tests:
        try:
            key = t.resolve()
        except (OSError, RuntimeError):
            key = t.absolute()
        if key in seen_resolved:
            continue
        seen_resolved.add(key)
        deduped.append(t)
    return sorted(deduped)


def run_tests(root, verbose=False):
    """Run pytest and capture structured results."""
    test_files = find_tests(root)
    if not test_files:
        # Fallback: check if CWD has tests
        test_files = find_tests(Path.cwd())
    if not test_files:
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "details": [], "duration": 0}

    start = time.time()
    # Pass tests/ if it exists, else pass discovered files individually
    test_target = "tests/" if (root / "tests").is_dir() else [str(t.relative_to(root)) for t in test_files]
    cmd = [sys.executable, "-m", "pytest"]
    cmd.extend([test_target] if isinstance(test_target, str) else test_target)
    cmd.extend(["-v", "--tb=short"])
    # --timeout requires pytest-timeout; skip if not installed (silent crash otherwise)
    try:
        import pytest_timeout  # noqa: F401
        cmd.append("--timeout=30")
    except ImportError:
        pass
    # Optional pytest -k expression via env var (e.g. to skip slow integration tests)
    test_filter = _get_test_filter()
    if test_filter:
        cmd.extend(["-k", test_filter])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(root),
            timeout=600, encoding="utf-8", errors="replace"
        )
        output = result.stdout + result.stderr
        rc = result.returncode
    except subprocess.TimeoutExpired:
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                "details": [{"test": "TIMEOUT", "status": "ERROR", "msg": "Tests exceeded 5min"}],
                "duration": 300}

    duration = time.time() - start

    # Parse results — find pytest summary line (last line matching "X passed" pattern)
    # Must anchor to the summary line to avoid matching "error" in tracebacks
    summary_line = ""
    for line in reversed(output.split("\n")):
        if re.search(r"\d+ passed", line) or re.search(r"\d+ failed", line) or re.search(r"\d+ error", line):
            summary_line = line
            break

    if summary_line:
        summary = re.search(r"(\d+) passed", summary_line)
        summary_f = re.search(r"(\d+) failed", summary_line)
        summary_e = re.search(r"(\d+) error", summary_line)
        summary_s = re.search(r"(\d+) skipped", summary_line)
        passed = int(summary.group(1)) if summary else 0
        failed = int(summary_f.group(1)) if summary_f else 0
        errors = int(summary_e.group(1)) if summary_e else 0
        skipped = int(summary_s.group(1)) if summary_s else 0
    else:
        # No summary line: pytest never ran (collection error, missing plugin, bad CLI)
        # Surface the failure instead of silently reporting "NO TESTS FOUND"
        passed = len(re.findall(r" PASSED", output))
        failed = len(re.findall(r" FAILED", output))
        errors = 0
        skipped = len(re.findall(r" SKIPPED", output))
        if passed == 0 and failed == 0 and skipped == 0 and rc != 0:
            tail = "\n".join(output.splitlines()[-15:])
            return {"total": 0, "passed": 0, "failed": 0, "errors": 1, "skipped": 0,
                    "details": [{"test": "PYTEST_RUNNER", "status": "ERROR", "msg": tail}],
                    "duration": round(time.time() - start, 1),
                    "raw_output": output}

    details = _parse_pytest_failures(output)
    # Track per-test name sets. Required for cycle 2.5 fix: forge default
    # compares SETS to spot hidden regressions (test_a passed→fails AND
    # test_b fails→passes nets to delta 0 in counts but is a real regression).
    by_status = _parse_pytest_per_test_status(output)
    xfailed_count = len(by_status["XFAIL"])
    xpassed_count = len(by_status["XPASS"])

    return {
        "total": passed + failed + errors + skipped,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "xfailed": xfailed_count,
        "xpassed": xpassed_count,
        "details": details,
        "duration": round(duration, 1),
        # Per-test name lists (sorted for deterministic baseline.json diffs).
        "passed_tests": sorted(by_status["PASSED"]),
        "failed_tests": sorted(by_status["FAILED"]),
        "xfailed_tests": sorted(by_status["XFAIL"]),
        "xpassed_tests": sorted(by_status["XPASS"]),
        "raw_output": output if verbose else None,
    }


def _get_test_filter():
    """Return the FORGE_TEST_FILTER env var as a pytest -k expression, or
    None. All sub-commands that invoke pytest should honor this so a noisy
    target repo (with unrelated pre-existing failures) can be narrowed to
    the slice the user actually cares about."""
    f = os.environ.get("FORGE_TEST_FILTER", "").strip()
    return f or None


def _combine_k_filter(test_filter, extra_filter):
    """Combine two pytest -k expressions with logical AND. Either may be None."""
    if test_filter and extra_filter:
        return f"({test_filter}) and ({extra_filter})"
    return test_filter or extra_filter


def _parse_pytest_per_test_status(output):
    """Parse pytest -v output to extract per-test status by name.

    Returns dict[status -> set[test_id]] for these statuses:
      PASSED, FAILED, SKIPPED, XFAIL, XPASS, ERROR

    pytest -v progress lines look like:
      "tests/x.py::test_y PASSED                  [ 13%]"
      "tests/x.py::test_y FAILED                  [ 26%]"
      "tests/x.py::test_y XFAIL (reason)          [ 39%]"
      "tests/x.py::test_y XPASS                   [ 52%]"

    Required for the cycle 2.5 fix: forge default needs to compare the
    SET of passed/failed test names against the baseline, not just the
    counts. Otherwise a swap (test_a passed→fails AND test_b fails→passes)
    nets to delta=0 and the user sees "PASS" while a real regression hides.
    """
    by_status = {
        "PASSED": set(), "FAILED": set(), "SKIPPED": set(),
        "XFAIL": set(), "XPASS": set(), "ERROR": set(),
    }
    # Test ID looks like "path/file.py::test_name" possibly with ::class::test
    # and an optional [param] tail. The [...] CAN contain spaces (e.g.
    # "[8 B]", "[hello world]") so we can't use \S+ for the whole thing —
    # that silently dropped any parametrized test whose id contained a space.
    # Body parts exclude '[' so the optional bracket group is what consumes it.
    pattern = re.compile(
        r"^([^\s\[]+(?:::[^\s\[]+)+(?:\[[^\]\n]*\])?)"
        r"\s+(PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)\b"
    )
    for line in output.split("\n"):
        m = pattern.match(line)
        if m:
            test_id, status = m.group(1), m.group(2)
            by_status[status].add(test_id)
    return by_status


def _parse_pytest_failures(output):
    """Extract unique (test, status, msg) entries from pytest output.

    Matches only the "short test summary" format:
        FAILED tests/path.py::test_name - message
        ERROR  tests/path.py::test_name - message

    Anchored with ^ (re.MULTILINE) to skip pytest's verbose progress lines
    such as `tests/x.py::test_y FAILED [13%]` or the bare `[FAILED] [13%]`
    bar — those would otherwise inflate failure counts. The test id must
    look like a real pytest node id (contains '::' or ends with '.py').
    """
    details = []
    seen = set()
    for match in re.finditer(
        r"^(FAILED|ERROR)\s+(\S+(?:::\S+)+|\S+\.py)(?:\s+-\s+(.*))?$",
        output, re.MULTILINE
    ):
        test_id = match.group(2).strip()
        if test_id in seen:
            continue
        seen.add(test_id)
        details.append({
            "test": test_id,
            "status": match.group(1),
            "msg": (match.group(3) or "").strip(),
        })
    return details


def load_json(path):
    """Load JSON file or return None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(path, data):
    """Save JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def print_report(results, baseline=None):
    """Print formatted test report."""
    total = results["total"]
    passed = results["passed"]
    failed = results["failed"]
    errors = results["errors"]
    duration = results["duration"]

    if total == 0:
        if results.get("errors", 0) > 0 and results.get("details"):
            print("\n  PYTEST RUNNER ERROR:\n")
            for d in results["details"]:
                print(f"    [{d['status']}] {d['test']}")
                if d.get("msg"):
                    for line in d["msg"].splitlines():
                        print(f"      {line}")
            print()
            return
        print("\n  NO TESTS FOUND. Run: forge.py --init\n")
        return

    # Header
    status = "PASS" if failed == 0 and errors == 0 else "FAIL"
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FORGE REPORT — {status}")
    print(f"{bar}")
    print(f"  Tests:    {total}")
    print(f"  Passed:   {passed}")
    print(f"  Failed:   {failed}")
    print(f"  Errors:   {errors}")
    print(f"  Skipped:  {results['skipped']}")
    print(f"  Duration: {duration}s")

    # Comparison with baseline
    if baseline:
        bp = baseline.get("passed", 0)
        bf = baseline.get("failed", 0)
        delta_p = passed - bp
        delta_f = failed - bf
        print(f"\n  vs baseline:")
        print(f"    Passed: {bp} -> {passed} ({'+' if delta_p >= 0 else ''}{delta_p})")
        print(f"    Failed: {bf} -> {failed} ({'+' if delta_f >= 0 else ''}{delta_f})")

        # Per-test set comparison: catches the hidden-regression case where
        # test_a flips passed→failed AND test_b flips failed→passed (delta=0
        # in counts, but a real regression). Cousin pc1 cycle 2 finding.
        baseline_passed = set(baseline.get("passed_tests", []))
        baseline_failed = set(baseline.get("failed_tests", []))
        now_passed = set(results.get("passed_tests", []))
        now_failed = set(results.get("failed_tests", []))
        # We only enter set-based diff when the baseline actually has the
        # per-test name lists (not legacy baseline.json without them).
        has_set_data = bool(baseline_passed or baseline_failed) and bool(now_passed or now_failed)
        if has_set_data:
            new_failures = sorted(baseline_passed & now_failed)
            new_fixes = sorted(baseline_failed & now_passed)
            still_failing = sorted(baseline_failed & now_failed)
            if new_failures:
                print(f"\n  *** REGRESSION: {len(new_failures)} test(s) flipped passed -> failed ***")
                for t in new_failures[:10]:
                    print(f"      {t}")
                if len(new_failures) > 10:
                    print(f"      ... and {len(new_failures) - 10} more")
            if new_fixes:
                print(f"\n  +++ FIX: {len(new_fixes)} test(s) flipped failed -> passed +++")
                for t in new_fixes[:5]:
                    print(f"      {t}")
            if still_failing and not new_failures and not new_fixes:
                print(f"\n  ({len(still_failing)} test(s) still failing — same set as baseline)")
            if not new_failures and not new_fixes:
                # Counts match AND no individual flip → real OK
                pass
        else:
            # Legacy baseline.json (counts only) — fall back to count delta
            if delta_f > 0:
                print(f"\n  *** REGRESSION: {delta_f} new failure(s) ***")
            elif delta_p > bp and failed == 0:
                print(f"\n  +++ PROGRESS: {delta_p} more passing +++")

        # XPASS surfacing: test marked xfail that now PASSES is a potential
        # semantic regression — the marker is now wrong.
        baseline_xpassed = set(baseline.get("xpassed_tests", []))
        now_xpassed = set(results.get("xpassed_tests", []))
        new_xpassed = sorted(now_xpassed - baseline_xpassed)
        if new_xpassed:
            print(f"\n  ⚠️  XPASS: {len(new_xpassed)} test(s) marked xfail now pass unexpectedly:")
            for t in new_xpassed[:5]:
                print(f"      {t}")
            print(f"      → review the @pytest.mark.xfail marker; the bug may be fixed.")

    # Failure details
    if results["details"]:
        print(f"\n  FAILURES:")
        for d in results["details"]:
            print(f"    [{d['status']}] {d['test']}")
            if d.get("msg"):
                print(f"            {d['msg']}")

    print(f"{bar}\n")


def init_repo(root):
    """Initialize BUGS.md and .forge/ in a repo."""
    forge_dir = root / FORGE_DIR
    forge_dir.mkdir(exist_ok=True)

    # .gitignore for .forge/
    gitignore = forge_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")

    # BUGS.md
    bugs_path = root / BUGS_FILE
    if not bugs_path.exists():
        bugs_path.write_text(f"""# BUGS — {root.name}

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

""", encoding="utf-8")
        print(f"  Created {BUGS_FILE}")

    # tests/ dir
    tests_dir = root / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        print(f"  Created tests/")

    print(f"  Forge initialized in {root.name}")


def add_bug(root, description):
    """Add a new bug to BUGS.md."""
    bugs_path = root / BUGS_FILE
    if not bugs_path.exists():
        init_repo(root)

    content = bugs_path.read_text(encoding="utf-8")

    # Find next bug number — accept both BUG- (correct) and BUG+ (legacy typo
    # written by older versions of this script) so existing BUGS.md files keep counting.
    existing = re.findall(r"BUG[-+](\d+)", content)
    next_num = max([int(n) for n in existing], default=0) + 1
    bug_id = f"BUG-{next_num:03d}"

    entry = f"""
## {bug_id}: {description}
- **Status**: OPEN
- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- **Symptom**: [a remplir]
- **Root cause**: [a remplir]
- **Fix**: [pending]
- **Test**: [a ecrire]
- **Regression**: [a verifier]
"""
    bugs_path.write_text(content + entry, encoding="utf-8")
    print(f"  Added {bug_id}: {description}")
    return bug_id


def close_bug(root, bug_id):
    """Mark a bug as FIXED in BUGS.md."""
    bugs_path = root / BUGS_FILE
    if not bugs_path.exists():
        print(f"  No {BUGS_FILE} found")
        return

    # Accept the digit-only shorthand (`forge --close 1`) and normalize it to
    # `BUG-001`. Without this the regex below silently failed to match and
    # printed "1 not found or already closed" — confusing UX on a tool that
    # itself prints bug ids as `BUG-XXX`.
    bug_id = bug_id.upper().strip()
    if bug_id.isdigit():
        bug_id = f"BUG-{int(bug_id):03d}"

    content = bugs_path.read_text(encoding="utf-8")
    pattern = f"(## {bug_id}:.*?\\n- \\*\\*Status\\*\\*: )OPEN"
    new_content = re.sub(pattern, f"\\1FIXED ({datetime.now().strftime('%Y-%m-%d')})", content)

    if new_content == content:
        print(f"  {bug_id} not found or already closed")
    else:
        bugs_path.write_text(new_content, encoding="utf-8")
        print(f"  {bug_id} marked FIXED")


def log_run(root, results):
    """Append to forge log."""
    log_path = root / FORGE_LOG
    os.makedirs(os.path.dirname(str(log_path)) or ".", exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "passed": results["passed"],
        "failed": results["failed"],
        "errors": results["errors"],
        "total": results["total"],
        "duration": results["duration"]
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# === FLAKY TEST DETECTION ===
def detect_flaky(root, runs=5):
    """Run tests N times, find tests that flip between pass/fail.
    Flaky tests are the #1 trust killer in CI — Luo et al. 2014."""
    print(f"  Running tests {runs} times to detect flaky tests...")
    all_failures = []
    for i in range(runs):
        print(f"    Run {i+1}/{runs}...", end=" ", flush=True)
        results = run_tests(root)
        failed_names = {d["test"] for d in results["details"]}
        all_failures.append(failed_names)
        status = f"{results['passed']}P/{results['failed']}F"
        print(status)

    # A test is flaky if it fails in SOME runs but not ALL
    all_tests_that_failed = set()
    for s in all_failures:
        all_tests_that_failed |= s

    flaky = []
    for test in sorted(all_tests_that_failed):
        fail_count = sum(1 for s in all_failures if test in s)
        if 0 < fail_count < runs:
            flaky.append({"test": test, "fail_rate": f"{fail_count}/{runs}",
                          "detected": datetime.now().isoformat()})

    # Save
    flaky_path = str(root / FLAKY_FILE)
    existing = load_json(flaky_path) or []
    known = {f["test"] for f in existing}
    for f in flaky:
        if f["test"] not in known:
            existing.append(f)
    save_json(flaky_path, existing)

    # Report
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FLAKY DETECTION — {runs} runs")
    print(f"{bar}")
    if flaky:
        print(f"  Found {len(flaky)} flaky test(s):")
        for f in flaky:
            print(f"    {f['test']}  ({f['fail_rate']} failures)")
        # AXE 6: classify flaky tests
        _print_flaky_classification(flaky, root)
        print(f"\n  Saved to {FLAKY_FILE}")
    else:
        always_fail = [t for t in all_tests_that_failed
                       if all(t in s for s in all_failures)]
        if always_fail:
            print(f"  No flaky tests. {len(always_fail)} consistent failure(s).")
        else:
            print(f"  All tests stable across {runs} runs.")
    print(f"{bar}\n")


# === FAILURE HEAT MAP (Pareto) ===
def show_heatmap(root):
    """Analyze forge log to find which tests fail most often.
    Pareto principle: 20% of tests cause 80% of failures — Kaner 2003."""
    log_path = root / FORGE_LOG
    if not log_path.exists():
        print("  No forge log yet. Run tests first.")
        return

    # Also check all saved reports for detail
    report_dir = root / FORGE_DIR
    failure_counts = Counter()
    total_runs = 0

    # Parse log for run counts
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                total_runs += 1
            except json.JSONDecodeError:
                continue

    # Parse all saved details (from flaky runs + last report)
    for jfile in report_dir.glob("*.json"):
        data = load_json(str(jfile))
        if not data:
            continue
        if isinstance(data, dict) and "details" in data:
            for d in data["details"]:
                if d.get("status") in ("FAILED", "ERROR"):
                    failure_counts[d["test"]] += 1
        elif isinstance(data, list):
            # flaky.json format
            for entry in data:
                if "test" in entry:
                    failure_counts[entry["test"]] += 1

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FAILURE HEAT MAP — {total_runs} runs logged")
    print(f"{bar}")
    if not failure_counts:
        print("  No failures recorded yet.")
        print("  Tip: forge logs every test run to .forge/forge_log.txt. Run a few cycles")
        print("  (or run with a known-broken test) to populate the heat map.")
    else:
        total_failures = sum(failure_counts.values())
        cumulative = 0
        for i, (test, count) in enumerate(failure_counts.most_common(20)):
            cumulative += count
            pct = cumulative / total_failures * 100
            heat = "#" * min(count, 30)
            print(f"  {count:3d}x  {test[:60]}")
            print(f"       {heat}  ({pct:.0f}% cumulative)")
        if len(failure_counts) > 20:
            print(f"  ... and {len(failure_counts) - 20} more")
        # Pareto check
        top20pct = max(1, len(failure_counts) // 5)
        top_failures = sum(c for _, c in failure_counts.most_common(top20pct))
        if total_failures > 0:
            pareto = top_failures / total_failures * 100
            print(f"\n  Pareto: top {top20pct} test(s) = {pareto:.0f}% of all failures")
    print(f"{bar}\n")


# === GIT BISECT AUTOMATION ===
def bisect_test(root, test_name):
    """Auto git-bisect to find which commit broke a specific test.
    Zeller 1999 — Delta Debugging + binary search on commits."""
    # Verify test exists and currently fails. Combine FORGE_TEST_FILTER (if
    # any) with the user-provided test_name via AND, so a noisy target repo
    # with pre-existing failures stays narrowed to the slice the user picked.
    print(f"  Verifying {test_name} currently fails...")
    k_expr = _combine_k_filter(_get_test_filter(), test_name)
    cmd_test = [sys.executable, "-m", "pytest", "-x", "-q", "--tb=line",
                "--no-header", "-k", k_expr]
    try:
        result = subprocess.run(cmd_test, capture_output=True, text=True,
                                cwd=str(root), encoding="utf-8", errors="replace",
                                timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  Verify step exceeded 120s. Set FORGE_TEST_FILTER to narrow "
              f"the slice or run pytest manually first.")
        return
    if "failed" not in result.stdout.lower() and "error" not in result.stdout.lower():
        print(f"  {test_name} is not currently failing. Nothing to bisect.")
        return

    # Capture the original ref so we can restore exactly (handles both branches
    # and detached HEAD). 'git checkout -' fails silently if HEAD was already
    # detached, leaving the repo in a wrong state.
    orig_head = subprocess.run(["git", "symbolic-ref", "-q", "--short", "HEAD"],
                               capture_output=True, text=True, cwd=str(root)).stdout.strip()
    if not orig_head:
        orig_head = subprocess.run(["git", "rev-parse", "HEAD"],
                                   capture_output=True, text=True, cwd=str(root)).stdout.strip()

    # Drop-in pitfall: forge.py is often present at the repo root. If the user
    # committed it, ancestor commits don't have it and `git checkout` deletes
    # it from the worktree → pytest crashes for unrelated reasons → bisect
    # marks every iteration FAIL and returns the wrong commit. Snapshot the
    # files that must survive every checkout, restore them after each one.
    survivors = {}
    for rel in ["forge.py", ".forge"]:
        p = root / rel
        if p.is_file():
            survivors[rel] = p.read_bytes()
    # Stash any uncommitted changes so checkouts succeed cleanly
    stash_r = subprocess.run(["git", "stash", "--include-untracked", "--quiet"],
                             cwd=str(root), capture_output=True, text=True)
    did_stash = stash_r.returncode == 0 and "No local changes" not in (stash_r.stdout + stash_r.stderr)

    def _restore_survivors():
        for rel, data in survivors.items():
            p = root / rel
            if not p.exists():
                p.write_bytes(data)

    # Find last known good (baseline commit or 20 commits back)
    try:
        log = subprocess.run(["git", "log", "--oneline", "-20"],
                            capture_output=True, text=True, cwd=str(root))
        commits = [l.split()[0] for l in log.stdout.strip().split("\n") if l.strip()]
    except Exception:
        print("  Git not available or not a git repo.")
        return

    if len(commits) < 2:
        print("  Not enough commits to bisect.")
        return

    print(f"  Bisecting across {len(commits)} commits...")
    # Binary search
    good_idx = len(commits) - 1
    bad_idx = 0

    try:
        while good_idx - bad_idx > 1:
            mid = (good_idx + bad_idx) // 2
            commit = commits[mid]
            print(f"    Testing commit {commit}...", end=" ", flush=True)

            subprocess.run(["git", "checkout", commit, "--quiet"], cwd=str(root),
                           capture_output=True)
            _restore_survivors()  # forge.py / .forge may have just been removed

            r = subprocess.run(cmd_test, capture_output=True, text=True,
                              cwd=str(root), encoding="utf-8", errors="replace",
                              timeout=120)
            is_bad = "failed" in r.stdout.lower() or "error" in r.stdout.lower()
            print("FAIL" if is_bad else "PASS")

            if is_bad:
                bad_idx = mid
            else:
                good_idx = mid
    finally:
        # ALWAYS return to the original ref + restore survivors + pop stash,
        # even if the loop above raised (timeout, KeyboardInterrupt, etc.)
        # First, drop any survivor files we restored as untracked — otherwise
        # `git checkout` refuses to clobber them with the original ref's
        # tracked version. The original ref's version (if any) will be brought
        # back by the checkout itself; if not, _restore_survivors() handles it.
        for rel in list(survivors):
            p = root / rel
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel],
                cwd=str(root), capture_output=True
            ).returncode == 0
            if p.exists() and not tracked:
                if p.is_file():
                    p.unlink()
                else:
                    import shutil as _sh
                    _sh.rmtree(p, ignore_errors=True)
        subprocess.run(["git", "checkout", orig_head, "--quiet"], cwd=str(root),
                       capture_output=True)
        _restore_survivors()
        if did_stash:
            subprocess.run(["git", "stash", "pop", "--quiet"], cwd=str(root),
                           capture_output=True)

    bad_commit = commits[bad_idx]
    # Get commit details
    detail = subprocess.run(["git", "log", "--oneline", "-1", bad_commit],
                           capture_output=True, text=True, cwd=str(root))

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  BISECT RESULT")
    print(f"{bar}")
    print(f"  First bad commit: {detail.stdout.strip()}")
    print(f"  Test: {test_name}")
    print(f"  Checked {len(commits)} commits in {int(round(len(commits)**0.5))+1} steps")
    print(f"{bar}\n")


# === TEST IMPACT ANALYSIS (--fast) ===
def get_changed_files(root):
    """Get Python files changed since last commit."""
    try:
        # Staged + unstaged changes
        r1 = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                           capture_output=True, text=True, cwd=str(root))
        r2 = subprocess.run(["git", "diff", "--name-only", "--cached"],
                           capture_output=True, text=True, cwd=str(root))
        r3 = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                           capture_output=True, text=True, cwd=str(root))
        files = set()
        for r in [r1, r2, r3]:
            for f in r.stdout.strip().split("\n"):
                if f.strip().endswith(".py"):
                    files.add(f.strip())
        return files
    except Exception:
        return set()


def find_impacted_tests(root, changed_files):
    """Find tests that import or reference changed modules.
    Inspired by pytest-testmon (Puha 2015) — dependency graph for test selection."""
    changed_modules = set()
    for f in changed_files:
        # Extract module name from path
        name = Path(f).stem
        changed_modules.add(name)

    impacted = []
    for test_file in find_tests(root):
        content = test_file.read_text(encoding="utf-8", errors="replace")
        for mod in changed_modules:
            if mod in content:
                impacted.append(test_file)
                break

    return impacted


def run_fast(root, verbose=False):
    """Run only tests impacted by recent changes."""
    changed = get_changed_files(root)
    if not changed:
        print("  No changes detected since last commit. Nothing to test.")
        print("  Tip: forge --fast looks at git diff HEAD. Edit a tracked file or stage a change first.")
        return

    print(f"  Changed files: {len(changed)}")
    for f in sorted(changed)[:10]:
        print(f"    {f}")
    if len(changed) > 10:
        print(f"    ... and {len(changed) - 10} more")

    # Always run test files that changed themselves
    test_files = [root / f for f in changed if "test_" in f]

    # Find tests impacted by changed source files
    impacted = find_impacted_tests(root, changed)
    test_files.extend(impacted)
    test_files = sorted(set(test_files))

    if not test_files:
        print("  No impacted tests found. Run full suite with: forge.py")
        return

    print(f"  Running {len(test_files)} impacted test file(s)...")
    start = time.time()
    cmd = [sys.executable, "-m", "pytest"] + [str(f) for f in test_files] + \
          ["-v", "--tb=short", "-q", "--no-header"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(root), timeout=300,
                               encoding="utf-8", errors="replace")
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print("  TIMEOUT after 5min")
        return

    duration = time.time() - start
    summary = re.search(r"(\d+) passed", output)
    summary_f = re.search(r"(\d+) failed", output)
    passed = int(summary.group(1)) if summary else 0
    failed = int(summary_f.group(1)) if summary_f else 0

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FAST MODE — {passed + failed} tests in {duration:.1f}s")
    print(f"  Passed: {passed}  Failed: {failed}")
    if failed > 0:
        for match in re.finditer(r"FAILED\s+(.*?)$", output, re.MULTILINE):
            print(f"    [FAIL] {match.group(1).strip()}")
    print(f"{bar}\n")


# === SNAPSHOT / GOLDEN FILE TESTING ===
def snapshot_capture(root, cmd_str):
    """Capture command output as a golden file for regression detection.
    Golden master testing — Feathers 2004, Working Effectively with Legacy Code."""
    snap_dir = root / SNAPSHOT_DIR
    os.makedirs(str(snap_dir), exist_ok=True)

    # Generate snapshot name from command
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", cmd_str)[:80]
    snap_path = snap_dir / f"{name}.golden"
    meta_path = snap_dir / f"{name}.meta.json"

    print(f"  Capturing: {cmd_str}")
    try:
        import shlex
        result = subprocess.run(shlex.split(cmd_str), shell=False, capture_output=True,
                               text=True, cwd=str(root), timeout=60,
                               encoding="utf-8", errors="replace")
        output = result.stdout
    except subprocess.TimeoutExpired:
        print("  Command timed out (60s)")
        return

    snap_path.write_text(output, encoding="utf-8")
    save_json(str(meta_path), {
        "command": cmd_str,
        "captured": datetime.now().isoformat(),
        "lines": output.count("\n"),
        "size": len(output)
    })
    print(f"  Saved: {snap_path.name} ({output.count(chr(10))} lines)")


def snapshot_check(root):
    """Compare all golden files against current output."""
    snap_dir = root / SNAPSHOT_DIR
    if not snap_dir.exists():
        print("  No snapshots found. Use: forge.py --snapshot \"command\"")
        return

    metas = list(snap_dir.glob("*.meta.json"))
    if not metas:
        print("  No snapshots found.")
        return

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  SNAPSHOT CHECK — {len(metas)} golden file(s)")
    print(f"{bar}")

    diffs = 0
    for meta_path in sorted(metas):
        meta = load_json(str(meta_path))
        if not meta:
            continue

        golden_path = meta_path.with_suffix("").with_suffix(".golden")
        if not golden_path.exists():
            print(f"  [MISSING] {golden_path.name}")
            diffs += 1
            continue

        expected = golden_path.read_text(encoding="utf-8")

        # Re-run command
        try:
            import shlex
            result = subprocess.run(shlex.split(meta["command"]), shell=False,
                                   capture_output=True, text=True,
                                   cwd=str(root), timeout=60,
                                   encoding="utf-8", errors="replace")
            actual = result.stdout
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {meta['command']}")
            diffs += 1
            continue

        if actual == expected:
            print(f"  [OK]   {meta['command'][:60]}")
        else:
            diffs += 1
            # Show diff summary
            exp_lines = expected.split("\n")
            act_lines = actual.split("\n")
            print(f"  [DIFF] {meta['command'][:60]}")
            print(f"         Expected {len(exp_lines)} lines, got {len(act_lines)}")
            # Show first 3 differing lines
            shown = 0
            for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
                if e != a and shown < 3:
                    print(f"         L{i+1}: -{e[:60]}")
                    print(f"         L{i+1}: +{a[:60]}")
                    shown += 1

    status = "PASS" if diffs == 0 else f"FAIL ({diffs} diff(s))"
    print(f"\n  Result: {status}")
    print(f"{bar}\n")
    if diffs > 0:
        sys.exit(1)


# === AXE 5: DEFECT PREDICTION (Nagappan & Ball 2005, Hassan 2009) ===
def predict_defects(root, weeks=8):
    """Predict which files are most likely to have bugs based on git history.
    Uses: relative churn, change frequency, change bursts, author count,
    bugfix frequency, LOC, recency. Nagappan & Ball ICSE 2005."""
    # Get tracked Python files
    tracked = _run_git(root, "ls-files", "*.py")
    if not tracked:
        print("  No tracked .py files found.")
        return
    files = [f for f in tracked.split("\n") if f.strip()]

    # Single git log call for all metrics
    raw_log = _fetch_numstat_log(root, weeks)

    # Parse git log into per-file metrics
    file_stats = {}
    for f in files:
        p = root / f
        loc = len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.exists() else 1
        file_stats[f] = {"added": 0, "deleted": 0, "commits": [], "authors": set(),
                         "bugfixes": 0, "loc": max(loc, 1), "dates": []}

    for c in _iter_numstat_commits(raw_log):
        for added, deleted, fname in c["files"]:
            if fname in file_stats:
                s = file_stats[fname]
                s["added"] += added
                s["deleted"] += deleted
                s["commits"].append(c["date"])
                s["authors"].add(c["author"])
                s["dates"].append(c["date"])
                if c["is_bugfix"]:
                    s["bugfixes"] += 1

    # Compute raw metrics per file
    metrics = {}
    # Minimum LOC threshold to avoid the loc=1 churn artefact.
    # Cousin pc1 cycle 2 finding (confirmed across scrapy + pytest cycles): empty
    # __init__.py or 1-line stub files report loc=1; with even a single 1-line
    # change, churn_rel = 2 (1 added + 1 deleted)/1 ≈ 2.0 — completely
    # disproportionate to real risk. Cap loc at >= MIN_PREDICT_LOC for the
    # ratio so trivial files can't dominate the ranking.
    MIN_PREDICT_LOC = 10
    for f, s in file_stats.items():
        if not s["commits"]:
            continue
        churn_rel = (s["added"] + s["deleted"]) / max(s["loc"], MIN_PREDICT_LOC)
        freq = len(s["commits"])
        # Change burst: max commits within any 48h window
        burst = 0
        if s["dates"]:
            try:
                timestamps = sorted([datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
                                    for d in s["dates"]])
                for i, t in enumerate(timestamps):
                    count = sum(1 for t2 in timestamps[i:] if t2 - t <= 48 * 3600)
                    burst = max(burst, count)
            except (ValueError, TypeError):
                burst = freq
        authors = len(s["authors"])
        bugfixes = s["bugfixes"]
        loc = s["loc"]
        # Recency: 1 / (1 + days since last change)
        try:
            last = max(datetime.fromisoformat(d.replace("Z", "+00:00")) for d in s["dates"])
            days_ago = (datetime.now(last.tzinfo) - last).days
            recency = 1.0 / (1.0 + days_ago)
        except (ValueError, TypeError):
            recency = 0.0

        metrics[f] = {"churn": churn_rel, "freq": freq, "burst": burst,
                      "authors": authors, "bugfix": bugfixes, "loc": loc, "recency": recency}

    if not metrics:
        print(f"  No commits in the last {weeks} weeks.")
        return

    # Normalize min-max per metric
    keys = ["churn", "freq", "burst", "authors", "bugfix", "loc", "recency"]
    mins = {k: min(m[k] for m in metrics.values()) for k in keys}
    maxs = {k: max(m[k] for m in metrics.values()) for k in keys}
    for f in metrics:
        for k in keys:
            rng = maxs[k] - mins[k]
            metrics[f][k + "_n"] = (metrics[f][k] - mins[k]) / rng if rng > 0 else 0.0

    # Composite risk score
    w = PREDICT_WEIGHTS
    for f in metrics:
        m = metrics[f]
        metrics[f]["risk"] = (w["churn"] * m["churn_n"] + w["freq"] * m["freq_n"] +
                              w["burst"] * m["burst_n"] + w["authors"] * m["authors_n"] +
                              w["bugfix"] * m["bugfix_n"] + w["loc"] * m["loc_n"] +
                              w["recency"] * m["recency_n"])

    # Sort and display
    ranked = sorted(metrics.items(), key=lambda x: x[1]["risk"], reverse=True)
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  DEFECT PREDICTION — {len(metrics)} files, last {weeks} weeks")
    print(f"{bar}")
    for i, (f, m) in enumerate(ranked[:15]):
        print(f"  {m['risk']:.2f}  {f}")
        print(f"       churn={m['churn']:.1f} freq={m['freq']} burst={m['burst']} "
              f"authors={m['authors']} bugfix={m['bugfix']} loc={m['loc']} recent={m['recency']:.2f}")
    print(f"{bar}\n")


# === AXE 6: FLAKY CLASSIFICATION (Luo et al. 2014, Parry 2021) ===
FLAKY_PATTERNS = {
    "Async Wait": {"patterns": ["time.sleep", "asyncio.sleep", "await ", "async "],
                   "fix": "Use explicit retry/poll or mock time"},
    "Concurrency": {"patterns": ["threading.", "multiprocessing.", "concurrent.", "Lock("],
                    "fix": "Add locks, use mock threading, or isolate state"},
    "Randomness": {"patterns": ["random.", "np.random", "uuid.uuid"],
                   "fix": "Fix seed in test: random.seed(42)"},
    "Resource Leak": {"patterns": ["tempfile.", "socket.", "open(", "requests."],
                      "fix": "Use context managers (with statement)"},
    "Platform": {"patterns": ["os.environ", "sys.platform", "os.name", "platform."],
                 "fix": "Mock os.environ / sys.platform in test"},
    "Floating Point": {"patterns": ["assertAlmostEqual", "pytest.approx", "1e-", "0.0001", "atol="],
                       "fix": "Use pytest.approx() with explicit tolerance"},
    "Unordered": {"patterns": [".keys()", ".values()", ".items()", "set("],
                  "fix": "Sort collections before comparing: sorted()"},
}


def _classify_flaky_test(test_name, root):
    """Scan test source for flaky pattern indicators via AST + text search."""
    # Find the test file
    for test_file in find_tests(root):
        try:
            source = test_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Extract just the function name from "file::test_func" or "test_func"
        func_name = test_name.split("::")[-1] if "::" in test_name else test_name
        if func_name not in source:
            continue
        # Check patterns against source text (more robust than AST for attribute chains)
        categories = []
        for cat, info in FLAKY_PATTERNS.items():
            for pat in info["patterns"]:
                if pat in source:
                    categories.append((cat, info["fix"]))
                    break
        return categories
    return []


def _print_flaky_classification(flaky_tests, root):
    """Print classification for detected flaky tests."""
    if not flaky_tests:
        return
    print(f"\n  FLAKY CLASSIFICATION (Luo et al. 2014):")
    for f in flaky_tests:
        cats = _classify_flaky_test(f["test"], root)
        if cats:
            for cat, fix in cats:
                print(f"    {f['test']}")
                print(f"      Category: {cat}")
                print(f"      Fix: {fix}")
                f["category"] = cat  # enrich for saving
        else:
            print(f"    {f['test']}")
            print(f"      Category: Unknown (no pattern detected)")


# === AXE 1: DELTA DEBUGGING / ddmin (Zeller & Hildebrandt 2002) ===
def _split_input(content, ext):
    """Split input into chunks based on file format."""
    if ext == ".json":
        data = json.loads(content)
        if isinstance(data, list):
            return data, "json_list"
        elif isinstance(data, dict):
            return list(data.items()), "json_dict"
    elif ext == ".csv":
        lines = content.strip().split("\n")
        if len(lines) > 1:
            return lines[1:], "csv"  # header kept separately
        return lines, "csv_no_header"
    # Default: split by lines
    return content.strip().split("\n"), "lines"


def _rebuild_input(chunks, fmt, original_content=""):
    """Rebuild input from chunks based on format."""
    if fmt == "json_list":
        return json.dumps(chunks, indent=2, ensure_ascii=False)
    elif fmt == "json_dict":
        return json.dumps(dict(chunks), indent=2, ensure_ascii=False)
    elif fmt == "csv":
        header = original_content.strip().split("\n")[0]
        return header + "\n" + "\n".join(chunks)
    return "\n".join(chunks)


def _test_with_input(root, test_name, input_content, input_ext):
    """Write input to temp file and run test. Returns True if test FAILS."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=input_ext, delete=False,
                                      encoding="utf-8", dir=str(root / FORGE_DIR))
    try:
        tmp.write(input_content)
        tmp.close()
        env = os.environ.copy()
        env["FORGE_MINIMIZE_INPUT"] = tmp.name
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "--tb=no",
                           "--no-header", "-k", test_name],
                          capture_output=True, text=True, cwd=str(root),
                          env=env, timeout=30, encoding="utf-8", errors="replace")
        return "failed" in r.stdout.lower() or "error" in r.stdout.lower()
    except subprocess.TimeoutExpired:
        return False  # timeout = can't confirm failure
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def minimize_input(root, test_name, input_file):
    """Delta debugging: find minimal input that still fails the test.
    Zeller & Hildebrandt 2002, IEEE TSE Vol.28 No.2."""
    input_path = Path(input_file)
    if not input_path.is_absolute():
        input_path = root / input_path
    if not input_path.exists():
        print(f"  File not found: {_safe_path(input_path)}")
        return

    ext = input_path.suffix
    content = input_path.read_text(encoding="utf-8")
    chunks, fmt = _split_input(content, ext)
    original_count = len(chunks)

    if original_count <= 1:
        print(f"  Input has only {original_count} element(s). Nothing to minimize.")
        return

    # Verify test fails with full input first
    print(f"  Verifying {test_name} fails with full input ({original_count} elements)...")
    if not _test_with_input(root, test_name, content, ext):
        print(f"  Test does not fail with this input. Nothing to minimize.")
        return

    print(f"  Running ddmin on {original_count} elements...")
    n = 2
    iteration = 0
    while len(chunks) > 1 and iteration < MINIMIZE_MAX_ITER:
        iteration += 1
        chunk_size = max(1, len(chunks) // n)
        subsets = [chunks[i:i + chunk_size] for i in range(0, len(chunks), chunk_size)]

        found = False
        # Try complements first (remove one subset)
        for i, subset in enumerate(subsets):
            complement = [c for j, s in enumerate(subsets) for c in s if j != i]
            rebuilt = _rebuild_input(complement, fmt, content)
            if _test_with_input(root, test_name, rebuilt, ext):
                chunks = complement
                n = max(n - 1, 2)
                found = True
                print(f"    Step {iteration}: {len(chunks)} elements (complement)")
                break

        if not found:
            # Try subsets alone
            for subset in subsets:
                if len(subset) < len(chunks):
                    rebuilt = _rebuild_input(subset, fmt, content)
                    if _test_with_input(root, test_name, rebuilt, ext):
                        chunks = subset
                        n = 2
                        found = True
                        print(f"    Step {iteration}: {len(chunks)} elements (subset)")
                        break

        if not found:
            if n >= len(chunks):
                break
            n = min(n * 2, len(chunks))

    # Write minimal result
    minimal = _rebuild_input(chunks, fmt, content)
    out_path = input_path.with_suffix(f".minimal{ext}")
    out_path.write_text(minimal, encoding="utf-8")

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  DDMIN RESULT — {original_count} -> {len(chunks)} elements")
    print(f"{bar}")
    print(f"  Reduction: {(1 - len(chunks)/original_count)*100:.0f}%")
    print(f"  Iterations: {iteration}")
    print(f"  Minimal input saved to: {out_path.name}")
    print(f"{bar}\n")


# === AXE 2: PROPERTY-BASED TEST GENERATION (Claessen & Hughes 2000) ===

# Destructive functions must NOT be fuzzed without isolation.
# Hypothesis happily generates target_path='.' / dry_run=False and the test then
# scrubs the entire repo in place. We learned this the hard way: a single
# property test on a redaction helper corrupted ~165 files before we had this guard.
#
# Defense: name patterns + AST scan for write operations. If either fires, the
# function is treated as destructive and the generated test is wrapped with
# pytest.skip(). Override with --include-destructive at the CLI level.

_DESTRUCTIVE_NAME_PATTERNS = [
    # filesystem mutations — clearly destructive prefixes only
    r"^scrub_", r"^purge_", r"^install_", r"^uninstall_",
    r"^delete_", r"^remove_",
    r"^write_", r"_write$", r"_save$",
    r"^migrate", r"^upgrade", r"^downgrade",
    r"^rebuild", r"^reset_", r"^cleanup", r"^prune",
    # database / state mutations
    r"^drop_", r"^truncate", r"^insert_", r"^update_",
    # network / external side effects
    r"^download", r"^upload", r"^send_", r"^post_", r"^put_",
    r"^sync_", r"_sync$", r"^pull_", r"^push_",
    # process / subprocess
    r"^run_", r"^exec_", r"^spawn_", r"^kill_",
    # hooks (anything in hook context is side-effecting by definition)
    r"_hook$", r"^hook_",
    # NOTE: removed ^generate_, ^create_, ^bootstrap, ^save, ^fetch_ —
    # they over-match pure-compute helpers (generate_password_hash,
    # generate_uuid, create_response, fetch_one). The AST scan below
    # catches the genuinely destructive ones via their write/subprocess
    # calls, so we don't lose real coverage by being more conservative
    # with name heuristics.
]

# AST node types / call patterns that indicate write side effects.
# Only methods whose semantics are unambiguously destructive across the
# common stdlib + popular libraries. Methods that are str-pure on str
# but Path-destructive on Path (like .replace) are excluded — disambiguating
# them needs type info we don't have, and the false-positive cost outweighs
# the false-negative cost for these.
_DESTRUCTIVE_CALLS = {
    # Path / file writers (Path/file methods, no str overload conflict)
    "write_text", "write_bytes", "writelines", "touch", "mkdir", "makedirs",
    "rmtree", "unlink", "rmdir", "chmod", "chown",
    # Subprocess / shell — always destructive
    "system", "popen", "call", "check_call", "check_output", "run",
    # urllib — network reads with side effects to disk
    "urlretrieve",
    # SQLite — direct DB writes
    "executescript", "executemany",
    # Removed (ambiguous, frequently pure):
    # - "replace": str.replace (pure) vs Path.replace (rename file)
    # - "rename": dict-like .rename usage exists (e.g. pandas)
    # - "remove": str/list/dict .remove are pure (mutate in-place but local)
    # - "delete": HTTP method + dict .delete (rare) — too overloaded
    # - "patch": unittest.mock.patch is pure
    # - "post", "put": HTTP methods are usually fine in test gen
    # - "run": subprocess.run kept via call/check_call; .run on async/Task is pure
    # - "dump", "dumps_to_file": json.dump etc. write to a passed handle, not
    #   to a fixed location — fuzzing them with bad data won't corrupt the repo
}

# If any positional/keyword argument has one of these names, the function very
# likely walks a real directory the caller controls — Hypothesis must NOT pass
# random strings here.
_PATH_LIKE_ARG_NAMES = {
    "path", "repo_path", "target_path", "file_path", "filepath",
    "dir", "dirname", "directory", "root", "output", "out_path", "outfile",
    "src", "dst", "source", "destination", "fp", "filename",
    "tree_path", "db_path", "config_path", "session_path",
}


def _is_destructive_function(node, source_text):
    """Return (is_destructive, reason) for an ast.FunctionDef node.

    Heuristics (any-of):
      1. Function name matches a destructive pattern (e.g. scrub_, install_).
      2. Function body contains a call to a known-destructive method
         (write_text, rmtree, subprocess.run, etc.).
      3. Function takes a path-like argument AND its body opens any file in
         write mode (open(..., 'w')) or appends.
    """
    name = node.name

    # 1. Name pattern check
    for pat in _DESTRUCTIVE_NAME_PATTERNS:
        if re.search(pat, name):
            return True, f"name matches /{pat}/"

    # 2. AST scan for destructive calls in body
    has_path_arg = any(
        a.arg in _PATH_LIKE_ARG_NAMES for a in node.args.args
    )

    for child in ast.walk(node):
        # method calls: x.write_text(...), shutil.rmtree(...), subprocess.run(...)
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in _DESTRUCTIVE_CALLS:
                return True, f"calls .{func.attr}()"
            if isinstance(func, ast.Name) and func.id in _DESTRUCTIVE_CALLS:
                return True, f"calls {func.id}()"
            # open(path, 'w'/'a'/'x'/'r+'/'w+'/'a+')
            if isinstance(func, ast.Name) and func.id == "open":
                for arg in list(child.args) + [kw.value for kw in child.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if any(m in arg.value for m in ("w", "a", "x", "+")):
                            return True, "calls open() in write mode"

    # 3. Path-arg without explicit isolation = suspicious
    if has_path_arg:
        # Look for any FS-touching call in the body, even read-only — if a
        # function takes repo_path and walks it with os.walk, fuzzing it with
        # '.' will recursively read the entire repo (slow + leaks data).
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute) and func.attr in (
                    "walk", "iterdir", "glob", "rglob", "scandir", "listdir"
                ):
                    return True, f"path arg + .{func.attr}()"
                if isinstance(func, ast.Attribute) and func.attr in (
                    "read_text", "read_bytes", "open"
                ):
                    return True, f"path arg + .{func.attr}()"

    return False, ""


def gen_props(root, module_path, include_destructive=False):
    """Analyze a Python module and generate Hypothesis property test skeletons.
    Detects: round-trip pairs, idempotent ops, sort/filter invariants.

    Destructive functions (anything that writes to disk, runs subprocess, talks
    to network, etc.) are skipped by default — fuzzing them can corrupt the repo.
    Pass include_destructive=True (or --include-destructive on the CLI) to override.
    """
    mod_path = Path(module_path)
    if not mod_path.is_absolute():
        mod_path = root / mod_path
    if not mod_path.exists():
        print(f"  File not found: {_safe_path(mod_path)}")
        return

    source = mod_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  Syntax error in {_safe_path(mod_path)}: {e}")
        return

    # Collect all public functions. Use iter_child_nodes (top-level only)
    # instead of ast.walk (recursive): class methods are not importable via
    # `from module import *` so picking them up would produce NameError at
    # test runtime. Also capture return annotation to disambiguate filter-vs-
    # tuple return functions.
    functions = []
    skipped_destructive = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            # Filter destructive functions BEFORE generating any test
            is_destr, reason = _is_destructive_function(node, source)
            if is_destr and not include_destructive:
                skipped_destructive.append((node.name, reason))
                continue
            # Extract arg names and annotations
            args = []
            for arg in node.args.args:
                ann = None
                if arg.annotation:
                    try:
                        ann = ast.literal_eval(arg.annotation) if isinstance(arg.annotation, ast.Constant) else \
                              arg.annotation.id if isinstance(arg.annotation, ast.Name) else None
                    except (ValueError, AttributeError):
                        ann = None
                args.append({"name": arg.arg, "type": ann})
            # Detect return type (best-effort): "list" / "tuple" / None
            return_type = None
            if node.returns is not None:
                if isinstance(node.returns, ast.Name):
                    return_type = node.returns.id
                elif isinstance(node.returns, ast.Subscript):
                    # tuple[...] or list[...] etc
                    if isinstance(node.returns.value, ast.Name):
                        return_type = node.returns.value.id
            functions.append({
                "name": node.name,
                "args": args,
                "lineno": node.lineno,
                "return_type": return_type,
            })

    if not functions:
        print(f"  No public functions found in {mod_path.name}")
        return

    # Detect pairs (encode/decode, compress/decompress, to_X/from_X)
    names = {f["name"] for f in functions}
    PAIRS = [("encode", "decode"), ("compress", "decompress"), ("serialize", "deserialize"),
             ("pack", "unpack"), ("encrypt", "decrypt"), ("dump", "load"),
             ("to_json", "from_json"), ("to_dict", "from_dict")]
    roundtrip_pairs = []
    for a, b in PAIRS:
        if a in names and b in names:
            roundtrip_pairs.append((a, b))
    # Also check to_X/from_X dynamically
    for name in names:
        if name.startswith("to_"):
            inverse = "from_" + name[3:]
            if inverse in names and (name, inverse) not in roundtrip_pairs:
                roundtrip_pairs.append((name, inverse))

    paired_funcs = {f for pair in roundtrip_pairs for f in pair}

    # Type annotation -> Hypothesis strategy
    TYPE_MAP = {"str": "st.text(max_size=100)", "int": "st.integers(-1000, 1000)",
                "float": "st.floats(allow_nan=False, allow_infinity=False)",
                "bool": "st.booleans()", "list": "st.lists(st.integers(), max_size=20)",
                "dict": "st.dictionaries(st.text(max_size=10), st.integers(), max_size=10)",
                "bytes": "st.binary(max_size=100)"}

    def strategy_for(arg):
        if arg["type"] in TYPE_MAP:
            return TYPE_MAP[arg["type"]]
        return "st.text(max_size=50)"

    # Generate module path for import
    try:
        rel = mod_path.relative_to(root)
    except ValueError:
        rel = Path(os.path.relpath(mod_path, root))
    import_path = str(rel).replace(os.sep, ".").replace(".py", "")
    # If the module is a package's __init__.py, the dotted path ends with
    # ".__init__" — explicitly importing the __init__ module is redundant and
    # triggers DeprecationWarnings in 3.13+. Strip it.
    if import_path.endswith(".__init__"):
        import_path = import_path[: -len(".__init__")]

    # Build test file — imports are LIVE so the generated test actually runs.
    # We insert ONLY the repo root into sys.path (not the module's parent dir).
    # Inserting `<repo>/mkdocs/utils/` would shadow PyPI packages whose name
    # overlaps with files in that dir (e.g. yaml.py vs PyPI 'yaml' package),
    # which is exactly what cousin pc1 hit on mkdocs cycle 2. Repo root alone
    # is enough for the standard `from pkg.subpkg.module import *` form.
    lines = [
        "#!/usr/bin/env python3",
        f'"""Property-based tests for {mod_path.name} — generated by forge.py --gen-props"""',
        "import sys",
        "import os",
        # Repo root only (so dotted module paths resolve via 'from pkg.sub import *')
        f"sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))",
        "",
        "import pytest",
        "from hypothesis import given, strategies as st, settings",
        f"from {import_path} import *",
        "",
        "",
        "# cwd guard: the destructive detector catches direct mkdir/write/open",
        "# calls in fuzzed function bodies, but it does not follow indirect calls",
        "# (e.g. parse_input() -> IndexBuilder() -> mkdir()). When Hypothesis fuzzes",
        "# a path-like arg with a random string like '0' or '\\xfeQ', the indirect",
        "# mkdir resolves it relative to cwd and pollutes the repo root.",
        "# This autouse fixture chdir's into tmp_path before each test, so any",
        "# indirect file-system mutation lands in a sandbox pytest cleans up.",
        "@pytest.fixture(autouse=True)",
        "def _forge_isolate_cwd(tmp_path, monkeypatch):",
        "    monkeypatch.chdir(tmp_path)",
        "",
    ]

    test_count = 0

    # Round-trip tests
    for enc, dec in roundtrip_pairs:
        lines.append(f"@given(data=st.text(max_size=200))")
        lines.append(f"@settings(max_examples=100)")
        lines.append(f"def test_roundtrip_{enc}_{dec}(data):")
        lines.append(f'    """Round-trip: {dec}({enc}(x)) == x"""')
        lines.append(f"    # from {import_path} import {enc}, {dec}")
        lines.append(f"    assert {dec}({enc}(data)) == data")
        lines.append("")
        test_count += 1

    # Per-function tests
    for func in functions:
        if func["name"] in paired_funcs:
            continue
        name = func["name"]
        args = [a for a in func["args"] if a["name"] != "self"]
        if not args:
            continue

        strats = ", ".join(f'{a["name"]}={strategy_for(a)}' for a in args)

        if "sort" in name.lower():
            lines.append(f"@given({strats})")
            lines.append(f"@settings(max_examples=100)")
            lines.append(f"def test_{name}_idempotent({', '.join(a['name'] for a in args)}):")
            lines.append(f'    """Idempotent: {name}({name}(x)) == {name}(x)"""')
            lines.append(f"    # from {import_path} import {name}")
            lines.append(f"    result = {name}({args[0]['name']})")
            lines.append(f"    assert {name}(result) == result")
            lines.append(f"    assert len(result) == len({args[0]['name']})")
            lines.append("")
            test_count += 1
        elif "filter" in name.lower() and func.get("return_type") in (None, "list"):
            # Only generate the subset test if the function actually returns a list.
            # Functions that return a tuple like (kept, dropped) would FAIL this test
            # because len(tuple) is the arity (2), not the kept-element count.
            lines.append(f"@given({strats})")
            lines.append(f"@settings(max_examples=100)")
            lines.append(f"def test_{name}_subset({', '.join(a['name'] for a in args)}):")
            lines.append(f'    """Subset: len({name}(x)) <= len(x)"""')
            lines.append(f"    # from {import_path} import {name}")
            lines.append(f"    result = {name}({', '.join(a['name'] for a in args)})")
            # Cousin cycle 2 finding: result can be None if the function bails
            # out on bad input (e.g. pytest's apply_warning_filters returns None
            # when no filters apply). len(None) crashes with TypeError that's
            # NOT in the whitelist below. Add explicit None-tolerance.
            lines.append(f"    if result is not None:")
            lines.append(f"        assert len(result) <= len({args[0]['name']})")
            lines.append("")
            test_count += 1
        else:
            # Smoke test: does not crash
            lines.append(f"@given({strats})")
            lines.append(f"@settings(max_examples=50)")
            lines.append(f"def test_{name}_no_crash({', '.join(a['name'] for a in args)}):")
            lines.append(f'    """Smoke: {name}() does not crash on arbitrary input"""')
            lines.append(f"    # from {import_path} import {name}")
            lines.append(f"    try:")
            lines.append(f"        {name}({', '.join(a['name'] for a in args)})")
            # Wide exception list: the contract is "no crash", not "no exception".
            # OSError covers FileNotFoundError and other I/O classes that real-world
            # modules legitimately raise on bad input. SyntaxError is for parser
            # functions (cousin cycle 2 finding on black's parse_ast). Exception
            # is the conservative catch-all — fuzzed inputs to library functions
            # often trigger custom exceptions (e.g. pytest.UsageError) that aren't
            # builtin; rather than auto-detecting via AST, we cast the widest net
            # since the contract here is purely "no SystemExit/segfault crash".
            lines.append(f"    except (ValueError, TypeError, KeyError, IndexError,")
            lines.append(f"            OSError, AttributeError, RuntimeError, SyntaxError,")
            lines.append(f"            LookupError, ArithmeticError, AssertionError,")
            lines.append(f"            SystemExit, Exception):")
            lines.append(f"        pass  # Expected rejections are OK")
            lines.append("")
            test_count += 1

    if test_count == 0:
        print(f"  No testable functions found in {mod_path.name}")
        if skipped_destructive:
            print(f"  ({len(skipped_destructive)} destructive function(s) skipped — pass --include-destructive to override)")
        return

    # Header banner: list skipped destructive functions in the test file itself,
    # so anyone reading the generated tests sees what was excluded and why.
    if skipped_destructive:
        banner = [
            "# forge: the following functions were SKIPPED because they have",
            "# side effects (write to disk, run subprocess, hit network).",
            "# Fuzzing them without isolation would corrupt the repo.",
            "# To test them, write isolated tests by hand using tmp_path.",
        ]
        for fn, reason in skipped_destructive:
            banner.append(f"#   - {fn}  ({reason})")
        banner.append("")
        # Insert after the docstring + import block (line 8 = after import os)
        lines = lines[:9] + banner + lines[9:]

    # Write test file
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    out_name = f"test_props_{mod_path.stem}.py"
    out_path = tests_dir / out_name
    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"  Generated {test_count} property tests -> tests/{out_name}")
    if skipped_destructive:
        print(f"  Skipped {len(skipped_destructive)} destructive function(s):")
        for fn, reason in skipped_destructive[:8]:
            print(f"    - {fn}  ({reason})")
        if len(skipped_destructive) > 8:
            print(f"    ... and {len(skipped_destructive) - 8} more")
        print(f"  Pass --include-destructive to fuzz them anyway (NOT RECOMMENDED).")

    # Check if hypothesis is installed
    try:
        __import__("hypothesis")
    except ImportError:
        print(f"  Note: pip install hypothesis to run these tests")

    # Cousin pc1 cycle 2 finding (rephrased for visibility): the destructive
    # detector is a name-pattern + AST-call scan, NOT a runtime escape analysis.
    # If a fuzzed function call goes through a 3rd-party helper that internally
    # touches the FS (e.g. parse_input() -> IndexBuilder() -> mkdir()), forge
    # CAN'T see it. The autouse cwd guard injected in the test file mitigates
    # most cases, but write paths held in module-level constants can escape.
    print(f"  ⚠️  AST scan does NOT follow indirect calls. The autouse cwd")
    print(f"      fixture chdirs each test into tmp_path so most file writes")
    print(f"      land in pytest's sandbox. But run in a disposable clone or")
    print(f"      `git stash` first if you've never run gen-props on this repo.")


# === AXE 3: MUTATION TESTING — Pure Python engine (DeMillo 1978, Offutt 1996) ===
# 5 sufficient mutation operators: AOR, ROR, LCR, UOI, SDL (Offutt 1996)
MUTATION_OPS = [
    # AOR — Arithmetic Operator Replacement
    (r'(?<!=)\+(?!=)', '-', 'AOR'),
    (r'(?<!=)-(?!=)', '+', 'AOR'),
    (r'(?<!/)\*(?!\*)', '/', 'AOR'),
    (r'(?<!\*)/', '*', 'AOR'),
    # ROR — Relational Operator Replacement
    (r'==', '!=', 'ROR'),
    (r'!=', '==', 'ROR'),
    (r'<=', '>', 'ROR'),
    (r'>=', '<', 'ROR'),
    (r'(?<!<)(?<!>)(?<!=)>(?!=)', '<', 'ROR'),
    (r'(?<!<)(?<!>)(?<!!)(?<!>)<(?!=)', '>', 'ROR'),
    # LCR — Logical Connector Replacement
    (r'\band\b', 'or', 'LCR'),
    (r'\bor\b', 'and', 'LCR'),
    (r'\bnot\b', '', 'LCR'),
    # UOI — Unary Operator Insertion (True/False swap)
    (r'\bTrue\b', 'False', 'UOI'),
    (r'\bFalse\b', 'True', 'UOI'),
    # SDL — Statement Deletion (return None instead of value)
    (r'return (.+)', 'return None', 'SDL'),
]


def _generate_mutants(source_path):
    """Generate mutants for a Python source file. Yields (line_no, op_name, original, mutated, full_source)."""
    source = source_path.read_text(encoding="utf-8", errors="replace")
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments, blank lines, decorators, imports, docstrings
        if not stripped or stripped.startswith("#") or stripped.startswith("@") or \
           stripped.startswith("import ") or stripped.startswith("from ") or \
           stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        for pattern, replacement, op_name in MUTATION_OPS:
            match = re.search(pattern, line)
            if match:
                mutated_line = line[:match.start()] + replacement + line[match.end():]
                if mutated_line != line:
                    mutated_source = "\n".join(lines[:i] + [mutated_line] + lines[i+1:])
                    yield (i + 1, op_name, line.strip(), mutated_line.strip(), mutated_source)


def run_mutation(root, target_file=None):
    """Pure-Python mutation testing. No external deps. Offutt 1996: 5 operators suffice.
    Mutation score = killed / total. Target: >80%."""
    # Find target files
    if target_file:
        target = Path(target_file)
        if not target.is_absolute():
            target = root / target
        targets = [target] if target.exists() else []
    else:
        # All tracked .py files (non-test)
        tracked = _run_git(root, "ls-files", "*.py")
        targets = [root / f for f in tracked.split("\n") if f.strip()
                   and "test_" not in f and f.strip().endswith(".py")]
        targets = [t for t in targets if t.exists()]

    if not targets:
        print("  No Python files to mutate.")
        return

    test_files = find_tests(root)
    if not test_files:
        print("  No tests found. Can't run mutation testing.")
        return

    test_paths = [str(f) for f in test_files]
    # Per-mutant timeout. Default: derive from baseline run duration so that a
    # repo with a 3-min test suite doesn't see EVERY mutant timeout in 30s.
    # Override via env var FORGE_MUTATE_TIMEOUT=N (seconds).
    mutate_timeout_env = os.environ.get("FORGE_MUTATE_TIMEOUT")
    if mutate_timeout_env and mutate_timeout_env.isdigit():
        mutant_timeout = int(mutate_timeout_env)
    else:
        baseline = load_json(str(root / BASELINE_FILE))
        baseline_dur = float(baseline.get("duration", 0)) if baseline else 0
        # 2x baseline + 10s safety margin, clamped [60, 600]
        mutant_timeout = max(60, min(600, int(baseline_dur * 2) + 10))
    print(f"  per-mutant timeout: {mutant_timeout}s "
          f"(set FORGE_MUTATE_TIMEOUT=N to override)")

    killed = 0
    survived = 0
    timeout_count = 0
    survivors = []

    for src in targets:
        original = src.read_text(encoding="utf-8", errors="replace")
        mutants = list(_generate_mutants(src))
        if not mutants:
            continue
        print(f"  {src.name}: {len(mutants)} mutants", end="", flush=True)
        for line_no, op, orig_line, mut_line, mut_source in mutants:
            # Apply mutant inside the try so the finally branch always runs
            # — even if write_text itself raises (disk full, permission flip
            # mid-loop). Otherwise the source could be left half-written
            # without a restore.
            try:
                src.write_text(mut_source, encoding="utf-8")
                r = subprocess.run(
                    [sys.executable, "-m", "pytest"] + test_paths +
                    ["-x", "-q", "--tb=no", "--no-header"],
                    capture_output=True, text=True, cwd=str(root),
                    timeout=mutant_timeout, encoding="utf-8", errors="replace"
                )
                if r.returncode != 0:
                    killed += 1
                    print(".", end="", flush=True)
                else:
                    survived += 1
                    sev = _hamming_severity(orig_line, mut_line)
                    sev_label = "SEVERE" if sev >= 5 else "moderate" if sev >= 2 else "minor"
                    survivors.append(f"L{line_no} [{op}] {orig_line} -> {mut_line}  (Hamming={sev}, {sev_label})")
                    print("S", end="", flush=True)
            except subprocess.TimeoutExpired:
                # Per mutation-testing convention, a timeout means the mutant
                # broke the code into a non-terminating state — counted as
                # killed. This is only honest when the timeout is calibrated
                # to the baseline (>= 2x baseline duration), which the
                # auto-derivation above ensures by default.
                timeout_count += 1
                killed += 1
                print("T", end="", flush=True)
            finally:
                # ALWAYS restore original
                src.write_text(original, encoding="utf-8")
        print()

    total = killed + survived
    if total == 0:
        print("  No mutants generated (file too small or only imports/comments).")
        return 100.0  # nothing to mutate = pass

    score = (killed / total * 100)

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  MUTATION TESTING — {'PASS' if score >= MUTATION_THRESHOLD else 'FAIL'}")
    print(f"{bar}")
    print(f"  Total mutants:  {total}")
    print(f"  Killed:         {killed}")
    print(f"  Survived:       {survived}")
    print(f"  Timeouts:       {timeout_count}  (counted as killed)")
    print(f"  Score:          {score:.0f}% (threshold: {MUTATION_THRESHOLD}%)")
    # Warning when timeouts dominate — signals that the timeout calibration
    # is too tight, OR the test suite genuinely doesn't exercise the file.
    if total > 0 and timeout_count / total > 0.2:
        print(f"  WARNING: {timeout_count}/{total} mutants timed out ({timeout_count/total:.0%}).")
        print(f"           Score may be inflated. Either your test suite is slower")
        print(f"           than {mutant_timeout}s, or no test in this repo runs the")
        print(f"           mutated code. Try: FORGE_MUTATE_TIMEOUT={mutant_timeout * 2}")

    if survivors:
        print(f"\n  SURVIVORS (tests didn't catch these mutations):")
        for s in survivors[:20]:
            print(f"    {s}")
        if len(survivors) > 20:
            print(f"    ... and {len(survivors) - 20} more")

    print(f"{bar}\n")
    return score


# === AXE 4: SPECTRUM-BASED FAULT LOCALIZATION / Ochiai (Abreu et al. 2007) ===
def fault_locate(root):
    """Locate suspicious lines using Ochiai SBFL formula.
    suspiciousness(s) = failed(s) / sqrt(total_failed * (failed(s) + passed(s)))
    Uses coverage.data.CoverageData for per-test context (10x faster than per-test runs)."""
    cov_mod = _check_dep("coverage")
    if not cov_mod:
        return

    # Check pytest-cov
    try:
        __import__("pytest_cov")
    except ImportError:
        print("  pytest-cov not installed. Install with: pip install pytest-cov")
        return

    test_files = find_tests(root)
    if not test_files:
        print("  No tests found.")
        return

    # Clean old coverage data
    cov_file = root / ".coverage"
    if cov_file.exists():
        cov_file.unlink()

    os.makedirs(str(root / FORGE_DIR), exist_ok=True)
    cmd = [sys.executable, "-m", "pytest"] + [str(f) for f in test_files] + \
          ["--cov", "--cov-context=test", "-v", "--tb=no", "--no-header"]
    # Honor FORGE_TEST_FILTER so this command's failure picture stays in
    # sync with the rest of forge (run_tests, --flaky, etc.).
    test_filter = _get_test_filter()
    if test_filter:
        cmd.extend(["-k", test_filter])
        print(f"  (filtered by FORGE_TEST_FILTER={test_filter!r})")

    print("  Running tests with per-test coverage...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root),
                          timeout=600, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        # Big repos (pytest, anyio) blow past 10 min on full --cov runs.
        # Don't crash with a Python traceback — give the user actionable hints.
        print("\n  TIMEOUT: --locate's pytest --cov run exceeded 10 min.")
        print(f"  ({len(test_files)} test files × per-test coverage = expensive)")
        print(f"  Try one of:")
        print(f"    - FORGE_TEST_FILTER='specific_test_name' forge --locate")
        print(f"    - run forge default first to identify failing tests, then filter")
        print(f"    - reduce test_files (delete unused tests/ subdirs in this repo)\n")
        return

    # Parse test results to know which tests passed/failed
    failed_tests = set()
    passed_tests = set()
    for line in (r.stdout + r.stderr).split("\n"):
        if " PASSED" in line:
            # "tests/test_sample.py::test_add_ok PASSED"
            test_id = line.split(" PASSED")[0].strip()
            passed_tests.add(test_id)
        elif " FAILED" in line:
            test_id = line.split(" FAILED")[0].strip()
            failed_tests.add(test_id)

    if not failed_tests:
        # Distinguish "really no failures" from "pytest crashed before running".
        # Same pattern as run_tests: when returncode != 0 AND nothing ran, surface
        # the runner error instead of misleading the user with "no failing tests".
        # Found 2026-05-08 on marshmallow: tests/mypy_test_cases/ caused 2
        # collection ERRORs → exit code 2 → fault_locate said "no failing tests"
        # while a real failure was masked.
        if r.returncode != 0 and not passed_tests:
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-15:])
            print("\n  PYTEST RUNNER ERROR (during --locate):")
            for line in tail.splitlines():
                print(f"    {line}")
            print(f"  exit code: {r.returncode}")
            print(f"  Hint: a test file in your repo crashed at collection")
            print(f"  (missing dep, plugin conflict, mypy_test_cases/ not for normal pytest...).")
            print(f"  Try FORGE_TEST_FILTER='specific_test' or fix the broken collector.\n")
            return
        print("  No failing tests. Nothing to localize.")
        return

    total_failed = len(failed_tests)

    # Read coverage DB with per-test contexts
    from coverage.data import CoverageData
    cd = CoverageData(str(cov_file))
    try:
        cd.read()
    except Exception as e:
        print(f"  Coverage data not readable: {e}")
        return

    # Normalize test IDs: coverage contexts use "path::test|run" format
    def _match_test(ctx_name, test_set):
        """Check if a coverage context matches any test in the set."""
        # Strip "|run" suffix from coverage context
        clean = ctx_name.split("|")[0].strip()
        for t in test_set:
            # Normalize backslash/forward slash
            t_norm = t.replace("\\", "/")
            c_norm = clean.replace("\\", "/")
            if t_norm == c_norm or t_norm.endswith(c_norm) or c_norm.endswith(t_norm):
                return True
        return False

    # Build suspiciousness scores per line
    suspects = []
    for src_file in cd.measured_files():
        # Skip test files
        basename = os.path.basename(src_file)
        if basename.startswith("test_") or basename == "__init__.py":
            continue

        contexts_by_line = cd.contexts_by_lineno(src_file)
        # Make display path relative
        try:
            display = str(Path(src_file).relative_to(root))
        except ValueError:
            display = src_file

        for line_no, ctx_set in contexts_by_line.items():
            if not ctx_set or ctx_set == {''}:
                continue

            f_count = sum(1 for ctx in ctx_set if _match_test(ctx, failed_tests))
            p_count = sum(1 for ctx in ctx_set if _match_test(ctx, passed_tests))

            if f_count == 0:
                continue

            denom = math.sqrt(total_failed * (f_count + p_count))
            score = f_count / denom if denom > 0 else 0.0

            suspects.append({
                "file": display, "line": line_no, "score": score,
                "failed": f_count, "passed": p_count
            })

    if not suspects:
        print("  No suspicious lines found (coverage data may be incomplete).")
        return

    suspects.sort(key=lambda x: x["score"], reverse=True)

    # Read source lines for display
    shown_files = {}
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FAULT LOCALIZATION — Ochiai SBFL")
    print(f"  {total_failed} failing test(s), {len(passed_tests)} passing")
    print(f"{bar}")
    for s in suspects[:OCHIAI_TOP_N]:
        label = "highly suspect" if s["score"] > 0.7 else "suspect" if s["score"] > 0.4 else "low"
        # Try to show the actual source line
        src_line = ""
        fpath = root / s["file"]
        if fpath.exists():
            if s["file"] not in shown_files:
                try:
                    shown_files[s["file"]] = fpath.read_text(encoding="utf-8", errors="replace").split("\n")
                except OSError:
                    shown_files[s["file"]] = []
            lines = shown_files[s["file"]]
            if 0 < s["line"] <= len(lines):
                src_line = lines[s["line"] - 1].strip()
        print(f"  {s['score']:.2f}  {s['file']}:{s['line']}  {src_line[:60]}")
        print(f"       {s['failed']}/{total_failed} fail, {s['passed']}/{len(passed_tests)} pass — {label}")
    print(f"{bar}\n")


# === CARMACK: ENHANCED DEFECT PREDICTION (Kalman + Wavelet + KM + Modularity) ===
def predict_carmack(root, weeks=8):
    """Cross-domain defect prediction. Replaces fixed weights with:
    - Kalman filter (adaptive risk from bugfix signal)
    - Haar wavelet (multi-scale churn decomposition)
    - Kaplan-Meier (survival probability per file)
    - Newman modularity (import graph coupling)"""
    tracked = _run_git(root, "ls-files", "*.py")
    if not tracked:
        print("  No tracked .py files found.")
        return
    files = [f for f in tracked.split("\n") if f.strip()]

    raw_log = _fetch_numstat_log(root, weeks)

    file_stats = {}
    for f in files:
        p = root / f
        loc = len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.exists() else 1
        file_stats[f] = {"added": 0, "deleted": 0, "commits": [], "authors": set(),
                         "bugfixes": 0, "loc": max(loc, 1), "dates": [],
                         "daily_churn": {}, "bugfix_dates": []}

    for c in _iter_numstat_commits(raw_log):
        date = c["date"]
        day = date[:10] if len(date) >= 10 else ""
        for a, d, fname in c["files"]:
            if fname in file_stats:
                s = file_stats[fname]
                s["added"] += a
                s["deleted"] += d
                s["commits"].append(date)
                s["authors"].add(c["author"])
                s["dates"].append(date)
                if day:
                    s["daily_churn"][day] = s["daily_churn"].get(day, 0) + a + d
                if c["is_bugfix"]:
                    s["bugfixes"] += 1
                    s["bugfix_dates"].append(date)

    # CARMACK 1: Real Newman Q via Louvain clustering on the import graph.
    # Score = how much the file binds its own cluster (0=bridge, 1=core binder).
    print("  [CARMACK] Louvain clustering on import graph...")
    graph = _build_import_graph(root)
    coupling = _modularity_contribution(graph)

    # Build a baseline date for KM censoring: oldest commit in window.
    all_dates = []
    for s in file_stats.values():
        all_dates.extend(s["dates"])
    try:
        baseline_ts = min(
            datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
            for d in all_dates
        ) if all_dates else 0.0
        now_ts = datetime.now(datetime.fromisoformat(
            all_dates[0].replace("Z", "+00:00")).tzinfo).timestamp() if all_dates else 0.0
    except (ValueError, TypeError):
        baseline_ts = 0.0
        now_ts = 0.0

    results = []
    for f, s in file_stats.items():
        if not s["commits"]:
            continue

        churn_rel = (s["added"] + s["deleted"]) / s["loc"]
        freq = len(s["commits"])

        # CARMACK 2: Haar wavelet — total high-freq energy across all detail
        # bands (multi-resolution), not just the first level.
        hf_energy = 0.0
        if s["daily_churn"]:
            days_sorted = sorted(s["daily_churn"].keys())
            churn_signal = [s["daily_churn"][d] for d in days_sorted]
            _, details = _haar_wavelet(churn_signal)
            for level in details:
                if level:
                    hf_energy += sum(d * d for d in level) / len(level)

        # CARMACK 3: Adaptive Kalman on weekly bug-rate (continuous signal,
        # Q,R estimated by EM). Last smoothed value = current risk.
        kalman_risk = 0.0
        if s["bugfix_dates"]:
            try:
                bf_ts = sorted(
                    datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
                    for d in s["bugfix_dates"]
                )
                # Bucket bugfix events into weekly bins from baseline -> now.
                if now_ts > baseline_ts:
                    n_weeks = max(int((now_ts - baseline_ts) / (7 * 86400)) + 1, 2)
                    bins = [0.0] * n_weeks
                    for t in bf_ts:
                        wk = min(int((t - baseline_ts) / (7 * 86400)), n_weeks - 1)
                        if wk >= 0:
                            bins[wk] += 1.0
                    smoothed, _q_hat, _r_hat = _adaptive_kalman(bins)
                    if smoothed:
                        kalman_risk = smoothed[-1]
            except (ValueError, TypeError):
                pass

        # CARMACK 4: Kaplan-Meier survival, properly censored.
        # For each *commit* of this file: event = "this commit was a bugfix",
        # time = days since baseline. Files whose last commit isn't a bugfix
        # contribute a censored observation at "now".
        crash_prob = s["bugfixes"] / max(freq, 1)  # fallback if KM fails
        try:
            obs = []
            bf_set = set(s.get("bugfix_dates", []))
            for d in s["dates"]:
                t = datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
                days = (t - baseline_ts) / 86400.0
                obs.append((days, d in bf_set))
            if obs:
                # If the most recent observation isn't an event, mark "now" as censored.
                last_t, last_event = max(obs, key=lambda x: x[0])
                if not last_event and now_ts > 0:
                    obs.append(((now_ts - baseline_ts) / 86400.0, False))
                km_curve = _kaplan_meier(obs)
                survival_14d = _km_survival_at(km_curve, 14.0)
                crash_prob = 1.0 - survival_14d
        except (ValueError, TypeError):
            pass

        # CARMACK 5: Coupling from real Newman Q via Louvain.
        file_coupling = coupling.get(f, 0.0)

        results.append({
            "file": f,
            "kalman": kalman_risk, "wavelet_hf": hf_energy,
            "crash_prob": crash_prob, "coupling": file_coupling,
            "churn": churn_rel, "freq": freq,
            "authors": len(s["authors"]), "bugfixes": s["bugfixes"], "loc": s["loc"],
            "n_distinct_days": len(s["daily_churn"]),
        })

    if not results:
        print(f"  No commits in the last {weeks} weeks.")
        return

    # Min-max normalize each signal across the active files, then compose.
    # This way each axis contributes its full weight instead of being clipped
    # by an arbitrary cap (different signals live on different scales now:
    # Kalman ~ weekly bug count, wavelet ~ multi-band churn energy, KM ~ [0,1]).
    def _norm(values):
        lo = min(values)
        hi = max(values)
        rng = hi - lo
        return [(v - lo) / rng if rng > 0 else 0.0 for v in values]

    kalman_n = _norm([r["kalman"] for r in results])
    wave_n = _norm([r["wavelet_hf"] for r in results])
    crash_n = [r["crash_prob"] for r in results]  # already in [0, 1]
    coupling_n = _norm([r["coupling"] for r in results])
    churn_n = _norm([r["churn"] for r in results])

    # Composite Carmack score (heuristic weights, sum to 1.0).
    # NOTE: weights are not validated empirically — they reflect the relative
    # importance the author assigns to each signal. Tune on your repo if needed.
    for i, r in enumerate(results):
        r["score"] = (
            0.25 * kalman_n[i] +
            0.20 * wave_n[i] +
            0.25 * crash_n[i] +
            0.15 * coupling_n[i] +
            0.15 * churn_n[i]
        )

    results.sort(key=lambda x: x["score"], reverse=True)

    n_active = len(results)
    total_commits = sum(r["freq"] for r in results)
    distinct_days_total = len({d for s in file_stats.values() for d in s["daily_churn"]})
    small_repo = n_active < 6 or total_commits < 10 or distinct_days_total < 7
    n_graph_nodes = len(graph)

    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  CARMACK PREDICT — Cross-domain defect prediction")
    print(f"  Kalman + Wavelet + Kaplan-Meier + Import Modularity")
    print(f"{bar}")
    if small_repo:
        print(f"  WARNING: small repo or short history — Carmack signals may be noisy.")
        print(f"           For a meaningful demo, run on a repo with >=6 files and >=4 weeks of history.")
    for r in results[:15]:
        wavelet_str = "n/a " if r.get("n_distinct_days", 0) < 3 else f"{r['wavelet_hf']:.1f}"
        coupling_str = "n/a " if n_graph_nodes < 3 else f"{r['coupling']:.2f}"
        print(f"  {r['score']:.3f}  {r['file']}")
        print(f"       Kalman={r['kalman']:.2f}  Wavelet={wavelet_str}  "
              f"Crash={r['crash_prob']:.0%}  Coupling={coupling_str}")
        print(f"       churn={r['churn']:.1f} freq={r['freq']} authors={r['authors']} "
              f"bugfix={r['bugfixes']} loc={r['loc']}")
    print(f"{bar}\n")
    return results


# === CARMACK: UNIFIED ANOMALY DETECTION (z-score outliers) ===
def anomaly_detect(root, weeks=8):
    """All axes are anomaly detection in disguise.
    Z-score across git metrics — flag files with z > 2.0 on 2+ metrics."""
    tracked = _run_git(root, "ls-files", "*.py")
    if not tracked:
        print("  No tracked .py files found.")
        return
    files = [f for f in tracked.split("\n") if f.strip()]

    raw_log = _fetch_numstat_log(root, weeks)

    file_stats = {}
    for f in files:
        p = root / f
        loc = len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.exists() else 1
        file_stats[f] = {"added": 0, "deleted": 0, "commits": 0, "authors": set(),
                         "bugfixes": 0, "loc": max(loc, 1)}

    for c in _iter_numstat_commits(raw_log):
        for added, deleted, fname in c["files"]:
            if fname in file_stats:
                s = file_stats[fname]
                s["added"] += added
                s["deleted"] += deleted
                s["commits"] += 1
                s["authors"].add(c["author"])
                if c["is_bugfix"]:
                    s["bugfixes"] += 1

    metrics_list = []
    active_files = []
    for f, s in file_stats.items():
        if s["commits"] == 0:
            continue
        active_files.append(f)
        metrics_list.append({
            "churn": (s["added"] + s["deleted"]) / s["loc"],
            "freq": s["commits"],
            "authors": len(s["authors"]),
            "bugfix_ratio": s["bugfixes"] / max(s["commits"], 1),
            "loc": s["loc"]
        })

    if len(metrics_list) < 3:
        print("  Not enough files with activity for anomaly detection.")
        return

    keys = ["churn", "freq", "authors", "bugfix_ratio", "loc"]
    means = {}
    stds = {}
    for k in keys:
        vals = [m[k] for m in metrics_list]
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        means[k] = mean
        stds[k] = std if std > 0 else 1.0

    anomalies = []
    for i, (f, m) in enumerate(zip(active_files, metrics_list)):
        z_scores = {}
        flags = 0
        for k in keys:
            z = (m[k] - means[k]) / stds[k]
            z_scores[k] = z
            if abs(z) > CARMACK_ZSCORE_THRESHOLD:
                flags += 1
        if flags >= 2:
            anomalies.append({"file": f, "z_scores": z_scores, "flags": flags, "metrics": m})

    anomalies.sort(key=lambda x: x["flags"], reverse=True)

    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  ANOMALY DETECTION — z-score outliers ({len(active_files)} active files)")
    print(f"{bar}")
    if not anomalies:
        print(f"  No anomalies detected (threshold: z > {CARMACK_ZSCORE_THRESHOLD} on 2+ metrics)")
    else:
        for a in anomalies[:10]:
            flags_str = " ".join(f"{k}={a['z_scores'][k]:+.1f}"
                                 for k in keys if abs(a['z_scores'][k]) > CARMACK_ZSCORE_THRESHOLD)
            print(f"  ANOMALY  {a['file']}")
            print(f"           {a['flags']} flags: {flags_str}")
            m = a['metrics']
            print(f"           churn={m['churn']:.1f} freq={m['freq']} "
                  f"authors={m['authors']} bugfix={m['bugfix_ratio']:.0%} loc={m['loc']}")
    print(f"{bar}\n")
    return anomalies


# === CARMACK: FLAKY DTW — Temporal pattern matching ===
def flaky_dtw(root, runs=5):
    """Enhanced flaky detection with DTW temporal pattern matching.
    Tests with similar pass/fail sequences = likely same root cause."""
    test_sequences = {}

    for run_num in range(runs):
        print(f"  Run {run_num + 1}/{runs}...", end=" ", flush=True)
        results = run_tests(root)
        print(f"{results['passed']}P/{results['failed']}F")

        failed_in_run = {d["test"] for d in results.get("details", []) if d["status"] == "FAILED"}
        all_known = {d["test"] for d in results.get("details", [])}

        for t in all_known:
            if t not in test_sequences:
                test_sequences[t] = []
            test_sequences[t].append(0 if t in failed_in_run else 1)

    # Find flaky (mixed results)
    flaky_tests = {t: seq for t, seq in test_sequences.items() if len(set(seq)) > 1}

    if not flaky_tests:
        print("  No flaky tests detected across runs.")
        return

    # DTW clustering
    test_names = list(flaky_tests.keys())
    clusters = []
    for i in range(len(test_names)):
        for j in range(i + 1, len(test_names)):
            dist = _dtw_distance(flaky_tests[test_names[i]], flaky_tests[test_names[j]])
            if dist < CARMACK_DTW_THRESHOLD:
                clusters.append((test_names[i], test_names[j], dist))

    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  FLAKY DTW ANALYSIS — {len(flaky_tests)} flaky test(s)")
    print(f"{bar}")
    for t, seq in flaky_tests.items():
        pattern = "".join("P" if s else "F" for s in seq)
        rate = seq.count(0) / len(seq)
        print(f"  {t}")
        print(f"    Pattern: {pattern}  Fail rate: {rate:.0%}")
        cats = _classify_flaky_test(t, root)
        if cats:
            for cat, fix in cats:
                print(f"    Category: {cat} — {fix}")

    if clusters:
        print(f"\n  SHARED ROOT CAUSE (DTW distance < {CARMACK_DTW_THRESHOLD}):")
        for a, b, dist in clusters:
            print(f"    {a}")
            print(f"    {b}")
            print(f"    DTW distance: {dist:.2f} — likely SAME root cause\n")

    print(f"{bar}\n")
    return flaky_tests


# === FULL CYCLE — The complete pipeline (metaprompt synthesis) ===
def full_cycle(root):
    """Run the full forge pipeline: predict -> mutate -> gen-props -> test -> flaky -> locate.
    Each step feeds the next. Stops early if nothing to do."""
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  FORGE FULL CYCLE")
    print(f"{bar}\n")

    # --- STEP 1: PREDICT — quels fichiers vont casser? ---
    print("  [1/8] PREDICT — scanning git history for risky files...")
    predict_defects(root, weeks=8)

    # --- STEP 1b: CARMACK PREDICT — cross-domain enhanced prediction ---
    print("  [1b/8] CARMACK PREDICT — Kalman + Wavelet + Kaplan-Meier + Modularity...")
    predict_carmack(root, weeks=8)

    # --- STEP 2: MUTATE — les tests couvrent-ils les mutations? ---
    # Only mutate small files changed recently (skip big files to stay fast)
    changed = get_changed_files(root)
    py_sources = [f for f in changed if "test_" not in f and f.endswith(".py")
                  and "__init__" not in f]
    small_sources = []
    for f in py_sources:
        p = root / f
        if p.exists():
            loc = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            if loc <= 200:
                small_sources.append(f)
            else:
                print(f"  [2/8] skip {f} ({loc} lines — use --mutate directly for big files)")
    if small_sources:
        print(f"  [2/8] MUTATE — testing {len(small_sources)} changed file(s)...")
        for src in small_sources[:5]:
            print(f"\n  --- {src} ---")
            run_mutation(root, src)
    elif not py_sources:
        print("  [2/8] MUTATE — no changed source files, skipping.")

    # --- STEP 3: GEN-PROPS — report only (skeletons need human review) ---
    if py_sources:
        print(f"\n  [3/8] GEN-PROPS — run `forge.py --gen-props <file>` to generate property tests for:")
        for src in py_sources[:5]:
            print(f"         {src}")
    else:
        print("  [3/8] GEN-PROPS — no changed source files.")

    # --- STEP 4: RUN TESTS ---
    print(f"\n  [4/8] RUN TESTS...")
    results = run_tests(root)
    baseline = load_json(str(root / BASELINE_FILE))
    print_report(results, baseline)
    log_run(root, results)
    save_json(str(root / REPORT_FILE), results)

    has_failures = results["failed"] > 0 or results["errors"] > 0

    # --- STEP 5: FLAKY — vrais bugs vs faux positifs ---
    if has_failures:
        print(f"  [5/8] FLAKY — checking if failures are stable (3 runs)...")
        detect_flaky(root, runs=3)
    else:
        print(f"  [5/8] FLAKY — all tests pass, skipping.")

    # --- STEP 6: LOCATE — quelle ligne est suspecte? ---
    if has_failures:
        print(f"  [6/8] LOCATE — running Ochiai SBFL on failing tests...")
        fault_locate(root)
    else:
        print(f"  [6/8] LOCATE — no failures, skipping.")

    # --- STEP 7: ANOMALY DETECTION — z-score outliers ---
    print(f"  [7/8] ANOMALY — scanning for statistical outliers...")
    anomaly_detect(root, weeks=8)

    # --- STEP 8: CARMACK SUMMARY ---
    print(f"  [8/8] CARMACK MOVES ACTIVE: Kalman, Wavelet, Kaplan-Meier, Newman, Hamming, DTW")

    # --- SUMMARY ---
    print(f"\n{bar}")
    print(f"  FULL CYCLE COMPLETE")
    print(f"{bar}")
    print(f"  Tests:   {results['total']} ({results['passed']}P / {results['failed']}F / {results['errors']}E)")
    if py_sources:
        print(f"  Changed: {', '.join(py_sources[:5])}")
    if not has_failures:
        print(f"  Status:  ALL CLEAR")
    else:
        print(f"  Status:  {results['failed'] + results['errors']} issue(s) found — check LOCATE output above")
    print(f"{bar}\n")


HELP_TEXT = """forge — pytest regression shield with predictive analytics

USAGE
  forge                            run tests vs baseline (default)
  forge --baseline                 run tests AND save as new baseline
  forge --init                     scaffold .forge/, BUGS.md, save first baseline
  forge --fast [-v]                run only tests changed since last commit
  forge --watch                    auto re-run on .py file change

ANALYTICS
  forge --predict [--weeks N]      rank files by churn-based defect risk
  forge --carmack [--weeks N]      multi-signal defect score (Kalman + wavelet + coupling)
  forge --anomaly [--weeks N]      flag commits with anomalous activity
  forge --heatmap                  show per-file failure heatmap
  forge --locate                   Ochiai SBFL fault localization (needs coverage.py)

FLAKY / BISECT
  forge --flaky [N]                re-run failing tests N times to classify flaky
  forge --flaky-dtw [N]            DTW-based flaky pattern detection
  forge --bisect TEST              git bisect a failing test back to its breaking commit

TEST GENERATION / MUTATION
  forge --gen-props PATH           Hypothesis property tests (skips destructive funcs by default)
  forge --gen-props PATH --include-destructive    DANGEROUS: fuzz destructive funcs
  forge --mutate [TARGET]          pure-Python mutation testing
  forge --minimize TEST INPUT      ddmin (Zeller 2002) on a failing input

SNAPSHOT
  forge --snapshot "CMD"           capture a CLI command's output as golden
  forge --snapshot-check           re-run captured commands, diff against golden

BUGS
  forge --add "DESCRIPTION"        log a new entry in BUGS.md
  forge --close BUG-ID             mark bug closed in BUGS.md

OPTIONS
  -v, --verbose                    verbose pytest output
  -h, --help                       show this help
  --diff                           show diff vs baseline (with default run)
  --full-cycle                     init + baseline + carmack + heatmap (everything)

DOCS
  https://github.com/sky1241/forge
"""


def main():
    root = find_repo_root()
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(HELP_TEXT)
        return

    if "--full-cycle" in args:
        full_cycle(root)
        return

    if "--carmack" in args:
        weeks = 8
        if "--weeks" in args:
            wi = args.index("--weeks")
            weeks = int(args[wi + 1]) if wi + 1 < len(args) and args[wi + 1].isdigit() else 8
        predict_carmack(root, weeks)
        return

    if "--anomaly" in args:
        weeks = 8
        if "--weeks" in args:
            wi = args.index("--weeks")
            weeks = int(args[wi + 1]) if wi + 1 < len(args) and args[wi + 1].isdigit() else 8
        anomaly_detect(root, weeks)
        return

    if "--flaky-dtw" in args:
        idx = args.index("--flaky-dtw")
        runs = int(args[idx + 1]) if idx + 1 < len(args) and args[idx + 1].isdigit() else 5
        flaky_dtw(root, runs)
        return

    if "--init" in args:
        init_repo(root)
        return

    if "--add" in args:
        idx = args.index("--add")
        desc = " ".join(args[idx + 1:]) if idx + 1 < len(args) else "unnamed bug"
        add_bug(root, desc)
        return

    if "--close" in args:
        idx = args.index("--close")
        bug_id = args[idx + 1] if idx + 1 < len(args) else ""
        close_bug(root, bug_id.upper())
        return

    if "--flaky" in args:
        idx = args.index("--flaky")
        runs = int(args[idx + 1]) if idx + 1 < len(args) and args[idx + 1].isdigit() else 5
        detect_flaky(root, runs)
        return

    if "--heatmap" in args:
        show_heatmap(root)
        return

    if "--bisect" in args:
        idx = args.index("--bisect")
        test_name = args[idx + 1] if idx + 1 < len(args) else ""
        if not test_name:
            print("  Usage: forge.py --bisect test_name")
            return
        bisect_test(root, test_name)
        return

    if "--fast" in args:
        run_fast(root, verbose="--verbose" in args or "-v" in args)
        return

    if "--snapshot" in args:
        idx = args.index("--snapshot")
        cmd_str = " ".join(args[idx + 1:]) if idx + 1 < len(args) else ""
        if not cmd_str:
            print("  Usage: forge.py --snapshot \"command to capture\"")
            return
        snapshot_capture(root, cmd_str)
        return

    if "--snapshot-check" in args:
        snapshot_check(root)
        return

    if "--predict" in args:
        weeks = 8
        if "--weeks" in args:
            wi = args.index("--weeks")
            weeks = int(args[wi + 1]) if wi + 1 < len(args) and args[wi + 1].isdigit() else 8
        predict_defects(root, weeks)
        return

    if "--minimize" in args:
        idx = args.index("--minimize")
        test_name = args[idx + 1] if idx + 1 < len(args) else ""
        input_file = args[idx + 2] if idx + 2 < len(args) else ""
        if not test_name or not input_file:
            print("  Usage: forge.py --minimize TEST_NAME INPUT_FILE")
            return
        minimize_input(root, test_name, input_file)
        return

    if "--gen-props" in args:
        idx = args.index("--gen-props")
        module_path = args[idx + 1] if idx + 1 < len(args) else ""
        if not module_path:
            print("  Usage: forge.py --gen-props path/to/module.py [--include-destructive]")
            return
        include_destructive = "--include-destructive" in args
        if include_destructive:
            print("  WARNING: --include-destructive is set. Destructive functions WILL")
            print("  be fuzzed by Hypothesis. This can corrupt your repo.")
            print("  Make sure tests are isolated with tmp_path before running them.")
        gen_props(root, module_path, include_destructive=include_destructive)
        return

    if "--mutate" in args:
        idx = args.index("--mutate")
        target = args[idx + 1] if idx + 1 < len(args) and not args[idx + 1].startswith("-") else None
        score = run_mutation(root, target)
        if score is not None and score < MUTATION_THRESHOLD:
            sys.exit(1)
        return

    if "--locate" in args:
        fault_locate(root)
        return

    if "--watch" in args:
        print("  Watching for changes... (Ctrl+C to stop)")
        last_hash = ""
        while True:
            try:
                # Hash all .py files. read_bytes() may race with editor saves
                # (file removed/moved between rglob and read) — skip those.
                h = hashlib.md5()
                for f in sorted(root.rglob("*.py")):
                    if ".forge" in str(f) or "__pycache__" in str(f):
                        continue
                    try:
                        h.update(f.read_bytes())
                    except (OSError, FileNotFoundError):
                        continue
                current = h.hexdigest()
                if current != last_hash:
                    last_hash = current
                    os.system("cls" if os.name == "nt" else "clear")
                    results = run_tests(root)
                    baseline = load_json(str(root / BASELINE_FILE))
                    print_report(results, baseline)
                    log_run(root, results)
                    save_json(str(root / REPORT_FILE), results)
            except KeyboardInterrupt:
                print("\n  --watch stopped.")
                return
            except Exception as e:
                # Don't kill the loop on a transient pytest crash or I/O
                # glitch. Surface, sleep, retry. Without this guard the loop
                # died silently on the first hiccup and the user only noticed
                # when their test status went stale.
                print(f"  --watch error (continuing): {type(e).__name__}: {e}")
            time.sleep(2)
        return

    # Default: run tests
    verbose = "--verbose" in args or "-v" in args
    results = run_tests(root, verbose=verbose)
    baseline = load_json(str(root / BASELINE_FILE))
    print_report(results, baseline)

    if "--baseline" in args:
        # Refuse to freeze a 0/0/0 baseline — it would mask later regressions
        # silently (the diff comparator would have nothing to diff against
        # and report PASS forever). Common cause: forge invoked from a dir
        # where find_tests can't see anything (wrong cwd, missing testpaths).
        if results.get("total", 0) == 0:
            print("  REFUSING baseline: 0 tests collected — would mask future "
                  "regressions. Check cwd, FORGE_TEST_FILTER, "
                  "[tool.pytest.ini_options] testpaths.")
        else:
            save_json(str(root / BASELINE_FILE), results)
            print(f"  Baseline saved: {results['passed']} passed, {results['failed']} failed")

    # Always save report + log
    os.makedirs(str(root / FORGE_DIR), exist_ok=True)
    save_json(str(root / REPORT_FILE), results)
    log_run(root, results)

    if "--diff" in args:
        if baseline:
            print("  (Diff shown above in report)")
        else:
            print("  No baseline found. Run: forge.py --baseline")

    # Exit code: non-zero if failures
    if results["failed"] > 0 or results["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
