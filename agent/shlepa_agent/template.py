"""Block-based request template renderer (v2).

The model-facing request is assembled from the ordered block list in
``[template].blocks`` of config.toml. Each block renders as
``{before}{content}{after}``; a block with empty content is dropped
together with its wrappers. The ``system`` and ``tools`` blocks render
into the system message; every other block renders into the per-phase
user message, both in list order.

Wrapper precedence (per block): phase code (``phase_wrappers`` argument)
> ``[phases.<id>.template.<block>]`` > ``[template].wrappers.<block>``.
A phase can therefore silence a wrapper (empty before/after) or write
its own.
"""

from __future__ import annotations

from shlepa_agent.config import AgentConfig, BlockWrapper

#: Blocks rendered into the system message (in config list order); every
#: other configured block renders into the user message.
SYSTEM_BLOCKS = ("system", "tools")

_EMPTY_WRAPPER = BlockWrapper()


def _wrapper_for(
    cfg: AgentConfig,
    phase_id: str,
    block: str,
    phase_wrappers: dict[str, BlockWrapper] | None,
) -> BlockWrapper:
    if phase_wrappers and block in phase_wrappers:
        return phase_wrappers[block]
    phase_cfg = cfg.phases.get(phase_id)
    if phase_cfg is not None and block in phase_cfg.template:
        return phase_cfg.template[block]
    return cfg.template.wrappers.get(block, _EMPTY_WRAPPER)


def _render_blocks(
    cfg: AgentConfig,
    phase_id: str,
    blocks: list[str],
    contents: dict[str, str],
    phase_wrappers: dict[str, BlockWrapper] | None,
) -> str:
    parts: list[str] = []
    for name in blocks:
        content = (contents.get(name) or "").strip("\n")
        if not content:
            continue
        wrapper = _wrapper_for(cfg, phase_id, name, phase_wrappers)
        parts.append(f"{wrapper.before}{content}{wrapper.after}".strip("\n"))
    return "\n\n".join(parts)


def render_system(
    cfg: AgentConfig,
    phase_id: str,
    contents: dict[str, str],
    phase_wrappers: dict[str, BlockWrapper] | None = None,
) -> str:
    """Render the system-message blocks (``system``, ``tools``) of a phase."""
    blocks = [b for b in cfg.template.blocks if b in SYSTEM_BLOCKS]
    return _render_blocks(cfg, phase_id, blocks, contents, phase_wrappers)


def render_user(
    cfg: AgentConfig,
    phase_id: str,
    contents: dict[str, str],
    phase_wrappers: dict[str, BlockWrapper] | None = None,
) -> str:
    """Render the per-phase user-message blocks (everything but system/tools)."""
    blocks = [b for b in cfg.template.blocks if b not in SYSTEM_BLOCKS]
    return _render_blocks(cfg, phase_id, blocks, contents, phase_wrappers)
