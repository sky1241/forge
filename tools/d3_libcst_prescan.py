"""Cycle 4 D-3 pre-scan: measure how many regex-generated mutants are
syntactically invalid before deciding to migrate to libcst.

This is a ONE-SHOT analysis tool, not part of the runtime package. Run
manually once; the output goes into `docs/D3_LIBCST_PRESCAN.md`.

Methodology:
  1. For each sample file, run forge._generate_mutants (regex-based).
  2. For each generated mutant source, attempt libcst.parse_module.
  3. Count valid (parses cleanly) vs invalid (raises ParserSyntaxError).
  4. Categorize invalid into top patterns (operator broken, string
     truncated, keyword swap that reaches an unreachable construct, etc).

Usage:
  cd ~/Bureau/forge
  .venv/bin/python tools/d3_libcst_prescan.py
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import libcst

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load forge.py without depending on conftest.py (this script lives outside tests/)
spec = importlib.util.spec_from_file_location("forge_root", REPO_ROOT / "forge.py")
assert spec is not None and spec.loader is not None
forge = importlib.util.module_from_spec(spec)
sys.modules["forge_root"] = forge
spec.loader.exec_module(forge)


SAMPLE_FILES = [
    REPO_ROOT / "tests" / "test_forge_destructive_skip.py",  # smallest first
    REPO_ROOT / "tests" / "test_typing.py",                  # tiny, but real
    REPO_ROOT / "forge.py",                                  # biggest
    REPO_ROOT / "tests" / "test_forge_real_algos.py",        # second biggest
]


def categorize_error(err_msg: str, orig_line: str, mut_line: str) -> str:
    """Bucket libcst parse errors into broad patterns."""
    em = err_msg.lower()
    if "unterminated" in em or "string" in em:
        return "string-truncated"
    if "expected an indented block" in em or "indentation" in em:
        return "indentation-broken"
    if "unexpected token" in em or "expected" in em and "got" in em:
        # Most common — we sub-bucket by the operation that produced the mutant
        if "->" in orig_line or "->" in mut_line:
            return "type-annotation-broken"
        return "syntax-token-broken"
    if "invalid syntax" in em:
        return "invalid-syntax-generic"
    return "other"


def scan_file(target: Path) -> dict[str, object]:
    """Run regex mutator on `target` and check each mutant against libcst.

    Returns a dict with counts + categorized invalids + 5 example invalids.
    """
    mutants = list(forge._generate_mutants(target))
    total = len(mutants)
    print(f"    {total} mutants generated, parsing each with libcst...",
          flush=True)
    valid = 0
    invalid = 0
    invalid_by_category: Counter[str] = Counter()
    invalid_by_op: Counter[str] = Counter()
    examples: list[dict[str, str]] = []

    for i, (line_no, op, orig_line, mut_line, mut_source) in enumerate(mutants):
        if i and i % 200 == 0:
            print(f"      progress: {i}/{total} (valid={valid} invalid={invalid})",
                  flush=True)
        try:
            libcst.parse_module(mut_source)
            valid += 1
        except libcst.ParserSyntaxError as e:
            invalid += 1
            cat = categorize_error(str(e), orig_line, mut_line)
            invalid_by_category[cat] += 1
            invalid_by_op[op] += 1
            if len(examples) < 5:
                examples.append({
                    "line_no": str(line_no),
                    "op": op,
                    "orig": orig_line,
                    "mut": mut_line,
                    "category": cat,
                    "error": str(e).split("\n")[0][:200],
                })

    return {
        "file": str(target.relative_to(REPO_ROOT)),
        "total_mutants": total,
        "valid": valid,
        "invalid": invalid,
        "invalid_pct": round(100.0 * invalid / total, 1) if total else 0.0,
        "invalid_by_category": dict(invalid_by_category),
        "invalid_by_op": dict(invalid_by_op),
        "examples": examples,
    }


def main() -> None:
    print(f"libcst version: {libcst._version.__version__}")  # type: ignore[attr-defined]
    print(f"forge: {REPO_ROOT}")
    print(f"sample files: {len(SAMPLE_FILES)}")
    print()

    results = []
    for f in SAMPLE_FILES:
        if not f.exists():
            print(f"  SKIP {f} — not found")
            continue
        print(f"  scanning {f.relative_to(REPO_ROOT)} ...")
        r = scan_file(f)
        results.append(r)
        print(f"    total={r['total_mutants']} valid={r['valid']} "
              f"invalid={r['invalid']} ({r['invalid_pct']}%)")

    print()
    print("=== SUMMARY ===")
    grand_total = sum(int(r["total_mutants"]) for r in results)  # type: ignore[arg-type]
    grand_invalid = sum(int(r["invalid"]) for r in results)  # type: ignore[arg-type]
    overall_pct = round(100.0 * grand_invalid / grand_total, 1) if grand_total else 0.0
    print(f"grand total mutants: {grand_total}")
    print(f"grand invalid: {grand_invalid} ({overall_pct}%)")
    print()

    # Aggregate categories across all files
    all_cats: Counter[str] = Counter()
    all_ops: Counter[str] = Counter()
    for r in results:
        for cat, n in r["invalid_by_category"].items():  # type: ignore[union-attr]
            all_cats[cat] += int(n)
        for op, n in r["invalid_by_op"].items():  # type: ignore[union-attr]
            all_ops[op] += int(n)
    print("Top categories of invalid mutants:")
    for cat, n in all_cats.most_common(5):
        print(f"  {n:5d}  {cat}")
    print()
    print("Invalid mutants by mutation operator:")
    for op, n in all_ops.most_common():
        print(f"  {n:5d}  {op}")
    print()

    # Recommendation
    if overall_pct < 5:
        rec = "MIGRATE-DIRECT (D-3 single commit, low risk)"
    elif overall_pct < 20:
        rec = "MIGRATE-CAREFUL (D-3a libcst alongside, D-3b regex removal after runtime validation)"
    else:
        rec = "STOP-DIALOGUE (regex mutator has structural quality gap; discuss before migration)"
    print(f"Recommendation: {rec}")
    print()
    print("Per-file detail:")
    for r in results:
        print(f"  {r['file']}: {r['invalid_pct']}% invalid")
        for ex in r["examples"]:  # type: ignore[union-attr]
            print(f"    L{ex['line_no']} [{ex['op']}] {ex['category']}")
            print(f"       orig: {ex['orig'][:80]}")
            print(f"       mut:  {ex['mut'][:80]}")
            print(f"       err:  {ex['error'][:140]}")


if __name__ == "__main__":
    main()
