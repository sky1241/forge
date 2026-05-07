"""BUG-102 — verify forge.gen_props() skips destructive functions.

Background : Hypothesis happily generated target_path='.' / dry_run=False
when forge --gen-props produced a property test for muninn.scrub_secrets().
The test then scrubbed the entire repo IN PLACE, corrupting 165 files with
literal '[REDACTED]' substitutions. Took several hours to recover.

Defense (forge.py _is_destructive_function): name patterns + AST scan.
This test locks in the defense so we never regress.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_forge():
    """Load the root forge.py as a module (independent of import path)."""
    spec = importlib.util.spec_from_file_location("forge_root", REPO_ROOT / "forge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def forge():
    return _import_forge()


def _build_node(forge, source, func_name):
    """Parse source and return the FunctionDef node for func_name."""
    import ast
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == func_name:
            return n
    raise AssertionError(f"function {func_name} not found")


# ── Name pattern detection ──────────────────────────────────────


def test_scrub_function_skipped_by_name(forge):
    src = """
def scrub_secrets(target_path, dry_run=False):
    pass
"""
    node = _build_node(forge, src, "scrub_secrets")
    is_destr, reason = forge._is_destructive_function(node, src)
    assert is_destr, "scrub_* must be detected as destructive"
    assert "scrub_" in reason


def test_install_function_skipped_by_name(forge):
    src = """
def install_hooks(repo_path):
    pass
"""
    node = _build_node(forge, src, "install_hooks")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


def test_purge_function_skipped_by_name(forge):
    src = "def purge_secrets_db(repo_path): pass"
    node = _build_node(forge, src, "purge_secrets_db")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


def test_bootstrap_function_skipped_by_name(forge):
    src = "def bootstrap_mycelium(repo_path): pass"
    node = _build_node(forge, src, "bootstrap_mycelium")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


def test_generate_function_skipped_by_name(forge):
    src = "def generate_root_mn(repo_path, files, mycelium): pass"
    node = _build_node(forge, src, "generate_root_mn")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


def test_hook_suffix_skipped(forge):
    src = "def session_end_hook(payload): pass"
    node = _build_node(forge, src, "session_end_hook")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


# ── AST-based detection (no name match needed) ─────────────────


def test_function_with_write_text_skipped(forge):
    src = """
from pathlib import Path
def innocent_name(data, where):
    p = Path(where)
    p.write_text(data)
"""
    node = _build_node(forge, src, "innocent_name")
    is_destr, reason = forge._is_destructive_function(node, src)
    assert is_destr, f"write_text() must be detected, got {reason!r}"
    assert "write_text" in reason


def test_function_with_subprocess_run_skipped(forge):
    src = """
import subprocess
def harmless(cmd):
    subprocess.run(cmd, shell=True)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, reason = forge._is_destructive_function(node, src)
    assert is_destr
    assert "run" in reason


def test_function_with_open_w_skipped(forge):
    src = """
def harmless(path, content):
    with open(path, "w") as f:
        f.write(content)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, reason = forge._is_destructive_function(node, src)
    assert is_destr


def test_function_with_rmtree_skipped(forge):
    src = """
import shutil
def harmless(d):
    shutil.rmtree(d)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert is_destr


def test_function_with_path_arg_and_walk_skipped(forge):
    """Even read-only walk on caller-supplied path is risky."""
    src = """
import os
def innocent(repo_path):
    for r, d, f in os.walk(repo_path):
        pass
"""
    node = _build_node(forge, src, "innocent")
    is_destr, reason = forge._is_destructive_function(node, src)
    assert is_destr, "walk on path-like arg must be detected"


# ── Pure functions must NOT be flagged ────────────────────────


def test_pure_string_function_not_skipped(forge):
    src = "def add(a, b): return a + b"
    node = _build_node(forge, src, "add")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert not is_destr


def test_redact_secrets_text_not_skipped(forge):
    """The pure-string secret redactor IS safe to fuzz."""
    src = """
import re
def redact_secrets_text(text):
    return re.sub(r'TOKEN', '[REDACTED]', text)
"""
    node = _build_node(forge, src, "redact_secrets_text")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert not is_destr


def test_count_chained_commands_not_skipped(forge):
    src = """
def count_chained_commands(text):
    if not text:
        return 0
    return text.count('&&') + text.count('||')
"""
    node = _build_node(forge, src, "count_chained_commands")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert not is_destr


def test_clamp_chained_commands_not_skipped(forge):
    src = """
def clamp_chained_commands(text, max_chains=30):
    n = text.count('&&') + text.count('||')
    if n > max_chains:
        return '[CLAMPED]', True
    return text, False
"""
    node = _build_node(forge, src, "clamp_chained_commands")
    is_destr, _ = forge._is_destructive_function(node, src)
    assert not is_destr


# ── Integration : gen_props on a fake module ───────────────────


def test_gen_props_skips_destructive_in_output(forge, tmp_path):
    """End-to-end: forge generates a test file that does NOT call scrub_*."""
    fake_module = tmp_path / "fakemod.py"
    fake_module.write_text(
        '''
def safe_add(a, b):
    return a + b

def scrub_files(target_path, dry_run=False):
    """DESTRUCTIVE — would corrupt the repo if fuzzed."""
    from pathlib import Path
    Path(target_path).write_text("destroyed")
''',
        encoding="utf-8",
    )

    # Run gen_props in a tmp root
    forge.gen_props(tmp_path, fake_module)

    out = tmp_path / "tests" / "test_props_fakemod.py"
    assert out.exists(), "forge should write a test file"
    content = out.read_text(encoding="utf-8")

    # safe_add should be tested
    assert "test_safe_add_no_crash" in content or "safe_add" in content

    # scrub_files MUST NOT appear as a callable test
    assert "scrub_files(" not in content, (
        "BUG-102 regression: forge generated a test that calls scrub_files()"
    )

    # The skipped function should appear in the banner / comment
    assert "scrub_files" in content, (
        "skipped functions should be listed in the file header so the user sees them"
    )


def test_gen_props_include_destructive_override(forge, tmp_path):
    """--include-destructive must actually let destructive functions through."""
    fake_module = tmp_path / "fakemod2.py"
    fake_module.write_text(
        "def scrub_files(path, dry_run=False): pass\n",
        encoding="utf-8",
    )

    forge.gen_props(tmp_path, fake_module, include_destructive=True)

    out = tmp_path / "tests" / "test_props_fakemod2.py"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    # When override is set, destructive functions ARE generated
    assert "scrub_files(" in content


def test_gen_props_real_muninn_does_not_call_scrub(forge, tmp_path):
    """The exact scenario that destroyed the repo: generate props for muninn.py
    and verify the output does NOT call scrub_secrets().

    We copy muninn.py into tmp_path so gen_props' relative_to() works.
    """
    real_muninn = REPO_ROOT / "engine" / "core" / "muninn.py"
    if not real_muninn.exists():
        pytest.skip("engine/core/muninn.py not present")

    # Mirror the real muninn.py inside tmp_path
    sub = tmp_path / "engine" / "core"
    sub.mkdir(parents=True)
    target = sub / "muninn.py"
    target.write_bytes(real_muninn.read_bytes())

    forge.gen_props(tmp_path, target)

    out = tmp_path / "tests" / "test_props_muninn.py"

    # Brick 18 widened the destructive patterns to cover ^scan_, ^analyze_,
    # ^bootstrap, ^generate_, ^install_, ^scrub_, ^purge_, ^cli_ etc. As a
    # result, ALL public functions in muninn.py now match the skip-list and
    # forge correctly emits "No testable functions found" without writing
    # any test file. Both outcomes are valid for BUG-102 fix:
    #   (a) file exists but contains no calls to forbidden functions, OR
    #   (b) file does not exist (ALL functions were skipped)
    if not out.exists():
        # All functions skipped — the strongest possible outcome
        return
    content = out.read_text(encoding="utf-8")

    # The killer functions MUST NOT be in the generated file
    forbidden = [
        "scrub_secrets(",
        "purge_secrets_db(",
        "install_hooks(",
        "bootstrap_mycelium(",
        "generate_root_mn(",
        "generate_winter_tree(",
    ]
    for fn in forbidden:
        assert fn not in content, (
            f"BUG-102 regression: forge generated {fn} for muninn.py — would corrupt the repo"
        )
