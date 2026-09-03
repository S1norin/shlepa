"""w3-3: failure ledger — repeated identical failures are compressed.

The 1st occurrence of a failed tool call is forwarded in full; from the
2nd identical (tool + args + normalized outcome) failure onward the
result body is replaced by a compact one-liner (family + exit code +
repeated N x). Knob SHLEPA_LEDGER (on by default; 0/false/off disables).
"""

from types import SimpleNamespace

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.state import (
    canonical_failure_key,
    extract_exit_code,
    ledger_enabled,
    normalize_ws,
)
from shlepa_agent.tools.base import AgentDeps, format_tool_result

_BASH_BODY = "$ ls nothere\n[cwd] /w\n[exit_code] 2\n[stdout]\n<empty>\n[stderr]\nls: nothere: No such file or directory"


def _ctx(tmp_path):
    deps = AgentDeps(workdir=tmp_path, cfg=load_config(), clock=lambda: 1.0)
    return SimpleNamespace(deps=deps), deps


def _call(ctx, body=_BASH_BODY, command="ls nothere", failed="exit 2"):
    return format_tool_result(
        ctx, "bash", body, 0.0, args={"command": command}, failed=failed
    )


# -- e2e-ish: format_tool_result over a shared run deps --------------------

def test_first_failure_never_compressed(tmp_path):
    ctx, deps = _ctx(tmp_path)
    out = _call(ctx)
    assert "No such file or directory" in out  # full body forwarded
    assert "[ledger]" not in out
    assert sum(deps.ledger.values()) == 1


def test_second_identical_failure_compressed(tmp_path):
    ctx, deps = _ctx(tmp_path)
    _call(ctx)
    out2 = _call(ctx)
    assert "REPEATED FAILURE (repeated 2x)" in out2
    assert "exit=2" in out2
    assert "No such file or directory" not in out2
    assert "[ledger] repeated 2x" in out2


def test_third_failure_counts(tmp_path):
    ctx, deps = _ctx(tmp_path)
    _call(ctx)
    _call(ctx)
    out3 = _call(ctx)
    assert "repeated 3x" in out3


def test_different_args_not_compressed(tmp_path):
    ctx, deps = _ctx(tmp_path)
    _call(ctx, command="ls nothere")
    out2 = _call(ctx, command="ls other")
    assert "No such file or directory" in out2
    assert "REPEATED" not in out2


def test_different_outcome_not_compressed(tmp_path):
    ctx, deps = _ctx(tmp_path)
    _call(ctx)
    out2 = _call(ctx, body=_BASH_BODY.replace("No such file", "Permission denied"))
    assert "REPEATED" not in out2
    assert "Permission denied" in out2


def test_whitespace_variants_are_identical(tmp_path):
    ctx, deps = _ctx(tmp_path)
    _call(ctx)
    out2 = _call(ctx, body=_BASH_BODY.replace("\n", "\n  \n"))
    assert "REPEATED FAILURE (repeated 2x)" in out2


def test_ledger_knob_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SHLEPA_LEDGER", "0")
    ctx, deps = _ctx(tmp_path)
    _call(ctx)
    out2 = _call(ctx)
    assert "No such file or directory" in out2
    assert "REPEATED" not in out2
    assert deps.ledger == {}


def test_success_results_not_ledgered(tmp_path):
    ctx, deps = _ctx(tmp_path)
    r1 = format_tool_result(ctx, "read", "same body", 0.0, args={"path": "a"})
    r2 = format_tool_result(ctx, "read", "same body", 0.0, args={"path": "a"})
    assert "REPEATED" not in r2
    assert deps.ledger == {}


# -- canonicalizer unit tests ----------------------------------------------

def test_canonical_key_stable_and_capped():
    k1 = canonical_failure_key("bash", {"command": "ls  x"}, "a  b", "exit 1")
    k2 = canonical_failure_key("bash", {"command": "ls x"}, "a\n b", "exit 1")
    assert k1 == k2
    assert len(canonical_failure_key("bash", {"c": "x" * 9000}, "b", "f")) <= 4000


def test_extract_exit_code_variants():
    assert extract_exit_code("[exit_code] 124\nrest") == "124"
    assert extract_exit_code("killed after 30s timeout (exit 124)") == "124"
    assert extract_exit_code("no code here") == "?"


def test_normalize_ws():
    assert normalize_ws("  a \n\n b\tc ") == "a b c"


def test_ledger_enabled_default_on(monkeypatch):
    monkeypatch.delenv("SHLEPA_LEDGER", raising=False)
    assert ledger_enabled()
    for v in ("0", "false", "OFF"):
        monkeypatch.setenv("SHLEPA_LEDGER", v)
        assert not ledger_enabled()
