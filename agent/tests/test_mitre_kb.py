"""Tests for the mitre_kb engine, tool, and +mitre-kb arm wiring.

Engine: id lookup (live + renumbered aliases), BM25 keyword ranking,
top-K cap, char cap, unknown-id note, read-only behavior. Wiring: off by
default (baseline byte-identical), arm-gated tool + prompt prefix.
"""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from shlepa_agent import mitre_kb as engine
from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.runner import _system_prompt
from shlepa_agent.tools import get_tools
from shlepa_agent.tools.base import AgentDeps
from shlepa_agent.toolsets import ARM_MITRE_KB

PHASES = ("plan", "work", "commit", "emergency")
TASK = "TASK"
BASE_TOOLS = ["read", "write", "edit", "bash"]


@pytest.fixture()
def kb():
    kb = engine.MitreKB(engine.KB_DIR)
    yield kb
    engine.reset_kb_cache()


def _ctx(tmp_path, cfg=None):
    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=lambda: 0.0)
    return SimpleNamespace(deps=deps)


def _kb_tree() -> dict[str, str]:
    out = {}
    for p in sorted(engine.KB_DIR.iterdir()):
        if p.is_file():
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# engine: id lookup
# ---------------------------------------------------------------------------


def test_id_lookup_exact(kb):
    mode, hits, unknown = kb.search("T1003.003")
    assert mode == "id"
    assert unknown == []
    assert hits[0].id == "T1003.003"
    assert hits[0].name == "NTDS"
    assert hits[0].parent_name == "OS Credential Dumping"


def test_id_lookup_resolves_renumbered_alias(kb):
    mode, hits, unknown = kb.search("T1562.001")
    assert mode == "id"
    assert hits[0].id == "T1685"
    assert hits[0].via_alias_of == "T1562.001"
    text = kb.render(mode, hits, unknown)
    assert "T1562.001 -> T1685" in text


def test_id_lookup_mixed_query(kb):
    mode, hits, unknown = kb.search("check T1021.001 and T1003.003 please")
    assert mode == "id"
    assert [h.id for h in hits] == ["T1021.001", "T1003.003"]


def test_unknown_id_is_noted_not_fatal(kb):
    mode, hits, unknown = kb.search("T9999.001 ntds")
    assert "T9999.001" in unknown
    # the keyword part still ranks something
    assert mode == "bm25"
    assert any(h.id == "T1003.003" for h in hits)
    text = kb.render(mode, hits, unknown)
    assert "T9999.001 not found" in text
    assert "not a v19.2 technique id" in text


# ---------------------------------------------------------------------------
# engine: BM25
# ---------------------------------------------------------------------------


def test_keyword_bm25_ntds(kb):
    mode, hits, _ = kb.search("ntds vssadmin secrets extraction")
    assert mode == "bm25"
    assert {h.id for h in hits[:2]} >= {"T1003.003"}


def test_keyword_bm25_rdp_ptt(kb):
    mode, hits, _ = kb.search("pass the ticket tcp 3389 rdp")
    assert mode == "bm25"
    assert {h.id for h in hits} & {"T1550.003", "T1021.001"}


def test_keyword_bm25_aws_passrole(kb):
    mode, hits, _ = kb.search("iam passrole adminrole cloud roles")
    assert mode == "bm25"
    assert {h.id for h in hits} & {"T1098.003", "T1078.004"}


def test_bm25_top_k_cap(kb):
    mode, hits, _ = kb.search("windows process")
    assert len(hits) <= engine.TOP_K


def test_no_match(kb):
    mode, hits, unknown = kb.search("zzqqx")
    assert mode == "none"
    assert hits == []
    text = kb.render(mode, hits, unknown)
    assert "no match" in text


def test_expansion_default_off_is_byte_identical_corpus(kb):
    """Shipped behavior: no expansion -> identical BM25 stats to before."""
    assert kb.expansion is None
    base = engine.MitreKB(engine.KB_DIR)
    assert kb._doc_terms == base._doc_terms
    assert kb._df == base._df
    assert kb._avgdl == base._avgdl


def test_expansion_hook_appends_to_bm25_corpus():
    """Dev/eval hook (issue #94): expansion text joins the doc text."""
    probe = "zyzwq"  # nonsense token: in no committed corpus text
    base = engine.MitreKB(engine.KB_DIR)
    assert base._bm25(probe) == []  # baseline: nothing matches
    exp = engine.MitreKB(engine.KB_DIR, expansion={"T1003": probe})
    scores = exp._bm25(probe)
    assert scores and scores[0][0] == "T1003"
    # ids without expansion text are unaffected
    assert all(tid != "T1003" or s > 0 for tid, s in scores)
    assert {tid for tid, _ in scores} == {"T1003"}


def test_full_mode_renders_verbatim_description(kb):
    mode, hits, unknown = kb.search("T1003.003")
    text = kb.render(mode, hits, unknown, full=True)
    assert kb.rows["T1003.003"]["description"].strip()[:80] in text
    assert "tactics:" in text
    assert "platforms:" in text
    # cheat mode does not carry the full description
    cheat_text = kb.render(mode, hits, unknown, full=False)
    assert len(cheat_text) < len(text)


def test_output_char_cap_drops_trailing_hits(kb):
    mode, hits, _ = kb.search("process injection windows")
    assert len(hits) >= 2
    text = kb.render(mode, hits, [], full=True, max_output=400)
    assert len(text) <= 400  # hard char cap
    assert "omitted by char cap" in text


# ---------------------------------------------------------------------------
# engine: read-only + cache
# ---------------------------------------------------------------------------


def test_tool_is_read_only(tmp_path):
    """The tool call must not write anywhere: workdir and KB untouched."""
    cfg = load_config()
    cfg.tools.mitre_kb.enabled = True
    before_dir = {p.name for p in tmp_path.iterdir()}
    before_kb = _kb_tree()
    from shlepa_agent.tools.mitre_kb import mitre_kb as mitre_kb_fn

    out = asyncio.run(mitre_kb_fn(_ctx(tmp_path, cfg), query="T1003.003"))
    assert out.startswith("[tool] mitre_kb(")
    assert "T1003.003" in out
    assert {p.name for p in tmp_path.iterdir()} == before_dir
    assert _kb_tree() == before_kb


def test_kb_cache_identity():
    assert engine.get_kb() is engine.get_kb()
    engine.reset_kb_cache()
    assert engine.get_kb() is engine.get_kb()  # re-cached after reset
    engine.reset_kb_cache()


# ---------------------------------------------------------------------------
# prompt prefix
# ---------------------------------------------------------------------------


def test_kb_prefix_content_and_stability():
    p1 = engine.kb_prefix()
    p2 = engine.kb_prefix()
    assert p1 == p2  # static content: KV-cache friendly
    assert "MITRE ATT&CK knowledge base" in p1
    assert "MITRE ATT&CK Enterprise v19.2" in p1  # the index header line
    assert "T1003.003 NTDS" in p1
    assert "T1562.001 -> T1685" in p1
    # every index line of the committed artifact is in the prefix
    index = (engine.KB_DIR / "index.txt").read_text(encoding="utf-8").strip("\n").splitlines()
    assert len(index) == 1 + engine.get_kb().live_patterns
    for line in index:
        assert line in p1
    assert p1.count(" -> ") >= 105


# ---------------------------------------------------------------------------
# config / arm wiring
# ---------------------------------------------------------------------------


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)
    cfg = load_config()
    assert cfg.tools.mitre_kb.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_TOOLS
        prompt = _system_prompt(cfg, get_phase(phase_id), TASK)
        assert "MITRE ATT&CK knowledge base" not in prompt
        assert "mitre_kb" not in prompt


def test_arm_env_enables_tool_and_prompt(monkeypatch):
    monkeypatch.setenv("AGENT_TOOLSET", ARM_MITRE_KB)
    cfg = load_config()
    assert cfg.arm == ARM_MITRE_KB
    assert cfg.tools.mitre_kb.enabled is True
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == BASE_TOOLS + ["mitre_kb"]
        prompt = _system_prompt(cfg, phase, TASK)
        assert "mitre_kb: search the pinned MITRE ATT&CK" in prompt
        assert "MITRE ATT&CK knowledge base" in prompt
        assert "T1003.003 NTDS" in prompt


def test_max_output_env_override(monkeypatch):
    monkeypatch.setenv("SHLEPA_MITRE_KB_MAX_OUTPUT", "1234")
    cfg = load_config()
    assert cfg.tools.mitre_kb.max_output == 1234
    monkeypatch.setenv("SHLEPA_MITRE_KB_MAX_OUTPUT", "not-a-number")
    assert load_config().tools.mitre_kb.max_output == 8000


def test_build_phase_agent_exposes_mitre_kb_tool(monkeypatch):
    """Regression: pydantic-ai must resolve the tool signature (RunContext
    annotation) — mirrors the code_search wiring regression test."""
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.model import TrackedModel
    from shlepa_agent.runner import build_phase_agent

    monkeypatch.setenv("AGENT_TOOLSET", ARM_MITRE_KB)
    cfg = load_config()
    model = TrackedModel(
        "m", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )
    agent = build_phase_agent(model, cfg, get_phase("work"), TASK)
    names = set(agent._function_toolset.tools)
    assert {"mitre_kb"} <= names
