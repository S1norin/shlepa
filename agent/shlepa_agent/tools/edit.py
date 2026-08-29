"""Edit tool: pi-style precise replacements (edits[] with optional 0-based line)."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path


class EditItem(BaseModel):
    """One replacement. ``line`` is 0-based and optional: without it ``oldText``
    must occur exactly once in the whole file; with it, ``oldText`` must occur
    exactly once within that single line."""

    oldText: str
    newText: str = ""
    line: int | None = None


def _lines_containing(text: str, needle: str) -> list[int]:
    return [i for i, l in enumerate(text.split("\n")) if needle in l]


def _line_start(text: str, lines: list[str], idx: int) -> int:
    start = 0
    for i in range(idx):
        start += len(lines[i]) + 1
    return start


def _line_hint(others: list[int]) -> str:
    if len(others) == 1:
        return f"; also found on line {others[0]}"
    return f"; also found on lines {', '.join(map(str, others))}"


async def edit(ctx: "RunContext[AgentDeps]", path: str, edits: list[EditItem]) -> str:
    """Make precise replacements in an existing file. Pass one or more edits;
    each oldText must be unique (exactly once in the file, or exactly once
    within the given 0-based line). All edits match the ORIGINAL file version
    and must not overlap."""
    p = resolve_path(path, ctx.deps.workdir)
    _log_event("tool_call", tool="edit", path=str(p), n_edits=len(edits))
    edits = [e if isinstance(e, EditItem) else EditItem.model_validate(e) for e in edits]
    if not p.exists():
        return f"File not found: {path}"
    if not edits:
        return "edits must not be empty"
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"Read error: {e}"

    lines = text.split("\n")
    total = len(lines)

    spans: list[tuple[int, int, int]] = []  # (start, end, edit index)
    for i, e in enumerate(edits):
        if not e.oldText:
            return f"edit #{i}: oldText must not be empty"
        if e.line is not None and "\n" in e.oldText:
            return (
                f"edit #{i}: oldText spans multiple lines but line={e.line} was "
                f"given; a line-scoped edit must fit on a single line"
            )
        if e.line is None:
            count = text.count(e.oldText)
            if count == 0:
                return f"edit #{i}: oldText not found in {path}"
            if count > 1:
                where = _lines_containing(text, e.oldText)
                where_txt = f" (lines {where})" if where else ""
                return (
                    f"edit #{i}: oldText found {count} times{where_txt}; "
                    f"extend it with context or pass line="
                )
            start = text.find(e.oldText)
            spans.append((start, start + len(e.oldText), i))
        else:
            if e.line < 0 or e.line >= total:
                return (
                    f"edit #{i}: line {e.line} out of range "
                    f"(file has {total} lines, 0-based)"
                )
            line_text = lines[e.line]
            count = line_text.count(e.oldText)
            if count == 0:
                hint = ""
                others = _lines_containing(text, e.oldText)
                if others:
                    hint = _line_hint(others)
                return f"edit #{i}: oldText not found on line {e.line}{hint}"
            if count > 1:
                return (
                    f"edit #{i}: oldText found {count} times on line {e.line}; "
                    f"add more context"
                )
            start = _line_start(text, lines, e.line) + line_text.find(e.oldText)
            spans.append((start, start + len(e.oldText), i))

    spans.sort()
    for (s1, e1, i), (s2, _e2, j) in zip(spans, spans[1:]):
        if s2 < e1:
            a, b = min(i, j), max(i, j)
            return (
                f"edits overlap (edit #{a} and edit #{b}); merge them or make "
                f"separate calls"
            )

    new_text = text
    for s, e, i in sorted(spans, reverse=True):
        new_text = new_text[:s] + edits[i].newText + new_text[e:]
    p.write_text(new_text, encoding="utf-8")
    return f"Replaced {len(spans)} block(s) in {path}"


EDIT_TOOL = Tool(
    name="edit",
    note="edit: precise replacements in an existing file (edits[] of "
    "{oldText, newText, line?}; oldText must be unique in the file, or within "
    "the given 0-based line).",
    run=edit,
)
