# Example: a tiny buggy calculator

A 2-file mini-project to feel forge's regression detection in 30 seconds.

## Setup

```bash
cd examples/calculator
git init -q && git add . && git -c user.email=t@t -c user.name=t commit -q -m "init"
forge --baseline      # snapshot 4 passing tests
```

## Demo: forge catches a real regression

```bash
# Introduce a bug in the source
sed -i 's/return a + b/return a - b/' calculator.py

# forge detects it without you re-running pytest manually
forge
```

Expected output (forge surfaces the regression with verbatim assertion):

```
*** REGRESSION: 1 test(s) flipped passed -> failed ***
    tests/test_calculator.py::test_add

  FAILURES:
    [FAILED] tests/test_calculator.py::test_add
            assert -1 == 3
```

Exit code: `1` (not `0` — so a CI script using `&&` chaining fails fast).

## Demo: forge --mutate finds the test gap

`calculator.py` has a `mul` function but no test for it.

```bash
forge --mutate --paths-to-mutate calculator.py
```

Expected: forge generates AST-aware mutants; the ones touching `add` are killed
by `test_add` (good), the ones touching `mul` survive (gap surfaced).

## Demo: forge --shield orchestrates predict → gen → run

```bash
forge --shield
```

Stage 1 (carmack) ranks files by defect risk. Stage 2 generates Hypothesis
property tests for risky files lacking matching tests. Stage 3 runs the
impacted tests via `--fast-deep`.
