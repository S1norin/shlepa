"""t3: block template rendering (order, empties, wrapper precedence)."""

from shlepa_agent.config import BlockWrapper, load_config
from shlepa_agent.template import SYSTEM_BLOCKS, render_system, render_user


def test_blocks_follow_config_order():
    cfg = load_config()
    out = render_user(
        cfg,
        "plan",
        {"phase_prompt": "PHASE STUFF", "extra": "EXTRA STUFF"},
    )
    assert out.index("EXTRA STUFF") < out.index("PHASE STUFF")


def test_empty_block_dropped_with_wrappers():
    cfg = load_config()
    out = render_user(cfg, "plan", {"extra": "DO THE EXTRA", "note": ""})
    assert "DO THE EXTRA" in out
    assert "NOTES" not in out  # wrapper of the empty block is dropped too


def test_all_blocks_empty_renders_empty():
    cfg = load_config()
    assert render_user(cfg, "plan", {}) == ""
    assert render_system(cfg, "plan", {}) == ""


def test_wrapper_precedence_phase_config_over_global():
    cfg = load_config()
    cfg.template.wrappers["task"] = BlockWrapper(before="GLOBAL\n", after="\n")
    cfg.phases["plan"].template["task"] = BlockWrapper(before="PHASE\n", after="\n")
    out = render_system(cfg, "plan", {"task": "T"})
    assert "PHASE" in out and "GLOBAL" not in out


def test_wrapper_precedence_phase_code_over_phase_config():
    cfg = load_config()
    cfg.phases["plan"].template["task"] = BlockWrapper(before="PHASE\n", after="\n")
    code_wrapper = {"task": BlockWrapper(before="CODE\n", after="\n")}
    out = render_system(cfg, "plan", {"task": "T"}, phase_wrappers=code_wrapper)
    assert "CODE" in out and "PHASE" not in out


def test_phase_template_only_applies_to_that_phase():
    cfg = load_config()
    cfg.phases["commit"].template["task"] = BlockWrapper(before="COMMIT-TASK\n", after="\n")
    out_plan = render_system(cfg, "plan", {"task": "T"})
    out_commit = render_system(cfg, "commit", {"task": "T"})
    assert "COMMIT-TASK" not in out_plan
    assert "COMMIT-TASK" in out_commit


def test_system_tools_task_go_to_system_message():
    cfg = load_config()
    system = render_system(
        cfg, "plan", {"system": "BASE", "tools": "bash note", "task": "T"}
    )
    user = render_user(
        cfg, "plan", {"system": "BASE", "tools": "bash note", "task": "T"}
    )
    assert "BASE" in system and "bash note" in system and "T" in system
    assert "BASE" not in user and "bash note" not in user and "T" not in user


def test_system_blocks_respect_config_list():
    cfg = load_config()
    assert set(SYSTEM_BLOCKS) <= set(cfg.template.blocks)
    # blocks not in the config list are ignored by both renderers
    out = render_user(cfg, "plan", {"ghost": "NOPE"})
    assert out == ""


def test_note_block_reserved_and_empty():
    cfg = load_config()
    assert "note" in cfg.template.blocks
    out = render_user(cfg, "plan", {"task": "T", "note": ""})
    assert "NOTES" not in out
