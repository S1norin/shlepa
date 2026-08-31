"""Fixed per-task time regime (v5).

All phase caps are FIXED constants. The only per-task value is the task time
limit T (the "horizon"), resolved in order:

    env (SLEPA_AGENT_TIMEOUT first) -> task.toml probe -> instruction text
    -> T_FALLBACK (600s)

Regime (seconds):

    plan     = PLAN_CAP   (60)  plan phase cap
    work     = WORK_CAP   (120) work phase cap per cycle
    review   = REVIEW_CAP (45)  review (commit) phase cap; the terminal
                                review may keep running until the hard stop
    margin   = MARGIN     (15)  hard stop = T - margin
    bash     = BASH_MAX   (30)  bash per-call cap (also the tool max)
    llm wall = LLM_WALL   (180) per-request wall-clock cap (open -> last
                                chunk), clamped to the remaining time

Phase caps are clamped to the remaining time at phase start (runner). There
is NO token budget and NO request-count limit: token usage is still logged
per request (telemetry / tie-break analysis) but never enforced. The request
gate (no new LLM request when fewer than gate_min seconds remain) stays.
Pure stdlib; no agent-specific imports.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass

T_MIN = 60.0
T_FALLBACK = 600.0

PLAN_CAP = 60.0
WORK_CAP = 120.0
REVIEW_CAP = 45.0
MARGIN = 15.0
BASH_MAX = 30.0
LLM_WALL = 180.0
GATE_EXTRA = 5.0  # gate_min = MARGIN + GATE_EXTRA (20s)

TIME_ENV_CANDIDATES = (
    "SLEPA_AGENT_TIMEOUT",  # set by the shlepa dev engine from task.toml
    "TASK_TIMEOUT_SEC",
    "TASK_TIME_LIMIT_SEC",
    "AGENT_TIMEOUT_SEC",
    "TIME_LIMIT_SEC",
    "TASK_LIMIT_SEC",
)
TOML_PROBE_PATHS = (
    "/app/task.toml",
    "/opt/harbor/local-agent/task.toml",
    "task.toml",
)

_TIME_RE = re.compile(
    r"(?:time\s+limit|time\s+budget|limit\s+of|finish(?:\s+the\s+task)?\s+within|you\s+have|within)\s*[:=]?\s+"
    r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|min|minutes)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Budget:
    """Per-task fixed regime. All times are seconds since run start."""

    T: float
    source: str
    margin: float
    hard: float
    plan: float
    work: float
    review: float
    bash_cap: float
    llm_wall: float
    gate_min: float

    def describe(self) -> str:
        return (
            f"task limit T={self.T:.0f}s (source={self.source}); "
            f"hard stop at {self.hard:.0f}s; "
            f"plan cap {self.plan:.0f}s; work cap {self.work:.0f}s per cycle; "
            f"review cap {self.review:.0f}s; bash cap {self.bash_cap:.0f}s; "
            f"no token/request limits (usage logged for analysis only)"
        )


def derive_budget(t: float, source: str = "derived") -> Budget:
    """Apply the fixed v5 regime to the task time limit T.

    Caps are constants; clamping to the remaining time happens at phase
    start (runner), not here.
    """
    T = max(T_MIN, float(t))
    return Budget(
        T=T,
        source=source,
        margin=MARGIN,
        hard=T - MARGIN,
        plan=PLAN_CAP,
        work=WORK_CAP,
        review=REVIEW_CAP,
        bash_cap=BASH_MAX,
        llm_wall=LLM_WALL,
        gate_min=MARGIN + GATE_EXTRA,
    )


def _env_float(names: tuple[str, ...]) -> tuple[float, str] | None:
    for name in names:
        raw = os.environ.get(name)
        if not raw:
            continue
        try:
            value = float(raw.strip())
        except ValueError:
            continue
        if value > 0:
            return value, f"env:{name}"
    return None


def _toml_probe() -> tuple[float, str] | None:
    candidates: list[str] = []
    task_dir = os.environ.get("TASK_DIR")
    if task_dir:
        candidates.append(os.path.join(task_dir, "task.toml"))
    candidates.extend(TOML_PROBE_PATHS)
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            value = data.get("agent", {}).get("timeout_sec")
            if isinstance(value, (int, float)) and value > 0:
                return float(value), f"toml:{path}"
        except (OSError, tomllib.TOMLDecodeError):
            continue
    return None


def extract_time_limit(instruction: str = "") -> tuple[float, str]:
    """Resolve the task time limit in seconds. Returns (limit, source)."""
    found = _env_float(TIME_ENV_CANDIDATES)
    if found is not None:
        return found
    found = _toml_probe()
    if found is not None:
        return found
    match = _TIME_RE.search(instruction or "")
    if match:
        value = float(match.group(1))
        if match.group(2).lower().startswith("min"):
            value *= 60.0
        return value, "text"
    return T_FALLBACK, "fallback"
