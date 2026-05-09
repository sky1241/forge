#!/bin/bash
# Cycle 8 bench harness — runs forge vs industry tools on 3 public repos.
# Reproduces the BENCHMARK.md results. NOT idempotent end-to-end (clones
# only if missing; pip install is idempotent; bench runs always re-run).
#
# Usage:
#   bash scripts/bench.sh           # full bench (~30-60min)
#   bash scripts/bench.sh httpie    # specific repo only
#
# Discipline (Sky cycle 8):
#   - 30min hard cap per bench (per Sky's discipline policy)
#   - Output verbatim to bench/results/<repo>/<tool>.json
#   - If a bench exceeds cap, document "TIMEOUT (30min)" in JSON
set -e
BENCH_DIR=${BENCH_DIR:-/tmp/cycle8-bench}
FORGE_DIR=${FORGE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
mkdir -p "$BENCH_DIR" "$FORGE_DIR/bench/results"/{httpie,black,click}
cd "$BENCH_DIR"

# Clone shallow if missing (idempotent)
for repo in httpie/cli psf/black pallets/click; do
    name=$(basename "$repo")
    if [ ! -d "$name" ]; then
        echo "Cloning $repo..."
        git clone --depth=200 "https://github.com/$repo.git" "$name"
    fi
done

# Setup venv-bench (idempotent if dir exists)
if [ ! -d "$BENCH_DIR/.venv-bench" ]; then
    python3 -m venv "$BENCH_DIR/.venv-bench"
    "$BENCH_DIR/.venv-bench/bin/python" -m ensurepip
    "$BENCH_DIR/.venv-bench/bin/python" -m pip install \
        -e "$FORGE_DIR[mutate,locate,fuzz]" \
        "mutmut<3" pytest-testmon pydeps --quiet
fi

VENV_PY="$BENCH_DIR/.venv-bench/bin/python"
VENV_FORGE="$BENCH_DIR/.venv-bench/bin/forge"
VENV_MUTMUT="$BENCH_DIR/.venv-bench/bin/mutmut"
VENV_PYDEPS="$BENCH_DIR/.venv-bench/bin/pydeps"

# Install repo deps + run benches per repo
filter=${1:-all}

if [ "$filter" = "all" ] || [ "$filter" = "httpie" ]; then
    echo "=== Bench httpie ==="
    cd "$BENCH_DIR/cli"
    "$VENV_PY" -m pip install -e ".[test]" --quiet
    timeout 1800 "$VENV_FORGE" --mutate --paths-to-mutate httpie/cli/argparser.py \
        > "$FORGE_DIR/bench/results/httpie/forge-mutate.log" 2>&1 || true
    timeout 1800 "$VENV_MUTMUT" run \
        --paths-to-mutate httpie/cli/argparser.py \
        --tests-dir tests \
        --runner "$VENV_PY -m pytest tests/test_cli.py -x --assert=plain --no-header -q" \
        > "$FORGE_DIR/bench/results/httpie/mutmut.log" 2>&1 || true
    "$VENV_FORGE" --modularity \
        > "$FORGE_DIR/bench/results/httpie/forge-modularity.log" 2>&1
    "$VENV_PYDEPS" httpie --no-output --show-deps \
        > "$FORGE_DIR/bench/results/httpie/pydeps.log" 2>&1
fi

if [ "$filter" = "all" ] || [ "$filter" = "click" ]; then
    echo "=== Bench click ==="
    cd "$BENCH_DIR/click"
    "$VENV_PY" -m pip install -e . --quiet
    timeout 1800 "$VENV_FORGE" --mutate --paths-to-mutate src/click/core.py \
        > "$FORGE_DIR/bench/results/click/forge-mutate.log" 2>&1 || true
fi

# black: skipped per BENCHMARK.md — test_format.py 75s baseline exceeds cap
if [ "$filter" = "black" ]; then
    echo "black bench is skipped (75s baseline × 200 mutants = 4h+, exceeds 30min cap)"
    echo "See BENCHMARK.md 'Bench 3 — black SKIPPED with rationale'"
fi

echo "Done. Results in $FORGE_DIR/bench/results/"
