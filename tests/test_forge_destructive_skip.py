"""Verify forge.gen_props() skips destructive functions.

Background: Hypothesis happily generates target_path='.' / dry_run=False when
asked to fuzz a redaction helper. The generated test then scrubs the entire
repo in place. We learned this the hard way (~165 files corrupted with literal
'[REDACTED]' substitutions, several hours to recover).

Defense (forge.py _is_destructive_function): name patterns + AST scan.
This test locks in the defense so we never regress.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def forge():
    """Yield the canonical forge module. Repo root is on sys.path via
    tests/conftest.py, so this is just `import forge` under its real name —
    no importlib alias dance. That's also what makes coverage work."""
    import forge as _forge
    return _forge


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
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr, "scrub_* must be detected as destructive"
    assert "scrub_" in reason


def test_install_function_skipped_by_name(forge):
    src = """
def install_hooks(repo_path):
    pass
"""
    node = _build_node(forge, src, "install_hooks")
    is_destr, _ = forge._is_destructive_function(node)
    assert is_destr


def test_purge_function_skipped_by_name(forge):
    src = "def purge_secrets_db(repo_path): pass"
    node = _build_node(forge, src, "purge_secrets_db")
    is_destr, _ = forge._is_destructive_function(node)
    assert is_destr


# NOTE: ^bootstrap and ^generate_ patterns were removed (they over-flag
# pure helpers like generate_password_hash, generate_uuid, bootstrap_app).
# The two tests below pin the new behavior: pure functions with these
# prefixes are NOT flagged. The AST scan still catches the genuinely
# destructive ones via their write/subprocess calls.

def test_generate_password_hash_not_skipped(forge):
    """generate_password_hash from werkzeug is pure compute (hashlib).
    Earlier versions over-flagged it via the ^generate_ pattern."""
    src = "def generate_password_hash(password, method='sha256'): return hashlib.sha256(password.encode()).hexdigest()"
    node = _build_node(forge, src, "generate_password_hash")
    is_destr, reason = forge._is_destructive_function(node)
    assert not is_destr, f"pure compute helper should not be flagged; reason={reason}"


def test_bootstrap_init_function_not_skipped(forge):
    """bootstrap_app() that just returns a configured object is pure init,
    no FS writes — must not be flagged."""
    src = "def bootstrap_app(config): app = Flask(__name__); return app"
    node = _build_node(forge, src, "bootstrap_app")
    is_destr, reason = forge._is_destructive_function(node)
    assert not is_destr, f"pure init should not be flagged; reason={reason}"


def test_generate_with_real_write_still_caught(forge):
    """A generate_*() that does write to disk is still caught — by the
    AST scan (write_text), not the (removed) name pattern."""
    src = (
        "def generate_report(target_path):\n"
        "    out = Path(target_path) / 'report.html'\n"
        "    out.write_text('<html></html>')\n"
    )
    node = _build_node(forge, src, "generate_report")
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr
    assert "write_text" in reason


def test_strip_url_with_str_replace_not_skipped(forge):
    """scrapy.utils.url.strip_url uses str.replace() — pure compute. Earlier
    versions over-flagged it via the .replace() call pattern (which is
    actually Path.replace() for renaming files)."""
    src = "def strip_url(url): return url.replace('http://', 'https://')"
    node = _build_node(forge, src, "strip_url")
    is_destr, reason = forge._is_destructive_function(node)
    assert not is_destr, f"str.replace() is pure; reason={reason}"


def test_hook_suffix_skipped(forge):
    src = "def session_end_hook(payload): pass"
    node = _build_node(forge, src, "session_end_hook")
    is_destr, _ = forge._is_destructive_function(node)
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
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr, f"write_text() must be detected, got {reason!r}"
    assert "write_text" in reason


def test_function_with_subprocess_run_skipped(forge):
    src = """
import subprocess
def harmless(cmd):
    subprocess.run(cmd, shell=True)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr
    assert "run" in reason


def test_function_with_open_w_skipped(forge):
    src = """
def harmless(path, content):
    with open(path, "w") as f:
        f.write(content)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr


def test_function_with_rmtree_skipped(forge):
    src = """
import shutil
def harmless(d):
    shutil.rmtree(d)
"""
    node = _build_node(forge, src, "harmless")
    is_destr, _ = forge._is_destructive_function(node)
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
    is_destr, reason = forge._is_destructive_function(node)
    assert is_destr, "walk on path-like arg must be detected"


# ── Pure functions must NOT be flagged ────────────────────────


def test_pure_string_function_not_skipped(forge):
    src = "def add(a, b): return a + b"
    node = _build_node(forge, src, "add")
    is_destr, _ = forge._is_destructive_function(node)
    assert not is_destr


def test_redact_secrets_text_not_skipped(forge):
    """The pure-string secret redactor IS safe to fuzz."""
    src = """
import re
def redact_secrets_text(text):
    return re.sub(r'TOKEN', '[REDACTED]', text)
"""
    node = _build_node(forge, src, "redact_secrets_text")
    is_destr, _ = forge._is_destructive_function(node)
    assert not is_destr


def test_count_chained_commands_not_skipped(forge):
    src = """
def count_chained_commands(text):
    if not text:
        return 0
    return text.count('&&') + text.count('||')
"""
    node = _build_node(forge, src, "count_chained_commands")
    is_destr, _ = forge._is_destructive_function(node)
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
    is_destr, _ = forge._is_destructive_function(node)
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
        "Regression: forge generated a test that calls a destructive function (scrub_files)"
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


