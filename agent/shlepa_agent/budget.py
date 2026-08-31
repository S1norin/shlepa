"""Adaptive per-task time budget.

All phase caps, deadlines and reserves are derived from the task time limit
T (and an optional token limit) instead of being hardcoded for 600s tasks.

Formulas (see docs/adaptive-budget.md):

    margin    = clamp(0.03*T, 5, 15)
    hard      = T - margin
    reserve   = min(0.10*T, 90) if 0.10*T >= 20 else 0   # finalize zone, not a phase
    core      = hard - reserve
    plan      = 0 if core < 90, else step 30 (T<200) / 45 (200<=T<300) / 60 (T>=300),
                capped at core - 60 (work 30s + commit 30s must still fit)
    work      = min(180, core - plan - 30)
    cycles    = max(1, floor((core - 30) / (plan + work)))
    commit    = cap clamp(0.20*T, 45, 120); deadline = min(work_end + cap, hard - reserve)
    bash      = clamp(0.20*T, 10, 240)
    finalize  = clamp(0.05*T, 5, 20)

Limit extraction order: env -> task.toml probe -> instruction text -> fallback.
The winning source is stored on the Budget so runs can be correlated later.
Pure stdlib; no agent-specific imports.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass

T_MIN = 60.0
T_FALLBACK = 600.0
TOKEN_FALLBACK = 300_000
TOKEN_FRACTION = 0.95

TIME_ENV_CANDIDATES = (
    "SLEPA_AGENT_TIMEOUT",  # set by the shlepa dev engine from task.toml
    "TASK_TIMEOUT_SEC",
    "TASK_TIME_LIMIT_SEC",
    "AGENT_TIMEOUT_SEC",
    "TIME_LIMIT_SEC",
    "TASK_LIMIT_SEC",
)
TOKEN_ENV_CANDIDATES = (
    "TOKEN_LIMIT",
    "TASK_TOKEN_LIMIT",
    "LLM_TOKEN_LIMIT",
    "TOKEN_BUDGET",
)
TOML_PROBE_PATHS = (
    "/app/task.toml",
    "/opt/harbor/local-agent/task.toml",
    "task.toml",
)

_TIME_RE = re.compile(
    r"(?:time\s+limit|time\s+budget|limit\s+of|finish(?:\s+the\s+task)?\s+within|you\s+have|"
    r"within)\s*[:=]?\s+"
    r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|min|minutes)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(
    r"token\s*(?:budget|limit)\s*(?:is|of|for)?\s*[:=]?\s*([\d][\d,]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BudgetForm:
    """All tuning knobs of the derivation formulas (v4 regime table).

    Defaults match the approved design; override per-deployment via
    ``[budget.form]`` in config.toml. ``plan_step_1``/``plan_step_2`` are
    (cap, T_threshold) pairs: below 200s plan is 30s, below 300s 45s, above
    that ``plan_max`` (60s).
    """

    t_min: float = 60.0
    t_fallback: float = 600.0
    token_fallback: float = 300_000.0
    token_fraction: float = 0.95
    margin_frac: float = 0.03
    margin_min: float = 5.0
    margin_max: float = 15.0
    reserve_frac: float = 0.10
    reserve_cap: float = 90.0
    reserve_min: float = 20.0
    plan_min_core: float = 90.0
    plan_step_1: tuple[float, float] = (30.0, 200.0)
    plan_step_2: tuple[float, float] = (45.0, 300.0)
    plan_max: float = 60.0
    plan_floor: float = 60.0  # work (30) + commit (30) must still fit after plan
    work_max: float = 180.0
    work_floor: float = 30.0
    commit_frac: float = 0.20
    commit_min: float = 45.0
    commit_max: float = 120.0
    commit_floor: float = 30.0  # minimum useful commit window
    bash_frac: float = 0.20
    bash_min: float = 10.0
    bash_max: float = 240.0
    finalize_frac: float = 0.05
    finalize_min: float = 5.0
    finalize_max: float = 20.0
    gate_extra: float = 5.0  # gate_min = margin + gate_extra


def _coerce_form(data: dict) -> "BudgetForm":
    """Build a BudgetForm from a raw dict, ignoring unknown keys."""
    valid = set(BudgetForm.__dataclass_fields__)
    kwargs = {k: v for k, v in (data or {}).items() if k in valid}
    for k in ("plan_step_1", "plan_step_2"):
        if k in kwargs:
            lo, hi = kwargs[k]
            kwargs[k] = (float(lo), float(hi))
    return BudgetForm(**kwargs)


@dataclass(frozen=True)
class Budget:
    """Derived per-task budget. All times are seconds since run start."""

    T: float
    source: str
    margin: float
    hard: float
    reserve: float
    core: float
    plan: float
    work: float
    max_cycles: int
    commit_cap: float
    commit_floor: float
    bash_cap: float
    finalize: float
    request_limit: int
    token_budget: int
    token_source: str
    gate_min: float

    @property
    def plan_enabled(self) -> bool:
        return self.plan > 0.0

    def describe(self) -> str:
        plan_txt = f"{self.plan:.0f}s" if self.plan else "off"
        return (
            f"task limit T={self.T:.0f}s (source={self.source}); "
            f"hard stop at {self.hard:.0f}s; plan {plan_txt}; "
            f"work {self.work:.0f}s per cycle, at most {self.max_cycles} cycle(s); "
            f"commit cap {self.commit_cap:.0f}s; bash cap {self.bash_cap:.0f}s; "
            f"token budget {self.token_budget} (source={self.token_source})"
        )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def derive_budget(
    t: float,
    token_limit: float | None = None,
    source: str = "derived",
    token_source: str = "derived",
    request_limit: int = 90,
    form: BudgetForm | None = None,
) -> Budget:
    """Derive all caps from the task time limit T and optional token limit."""
    f = form or BudgetForm()
    T = max(f.t_min, float(t))
    margin = _clamp(f.margin_frac * T, f.margin_min, f.margin_max)
    hard = T - margin

    r = f.reserve_frac * T
    reserve = min(r, f.reserve_cap) if r >= f.reserve_min else 0.0
    core = hard - reserve

    # Plan: fixed steps 30/45/60; dropped entirely when it cannot coexist
    # with a >=30s work phase and a >=30s commit.
    plan = 0.0
    if core >= f.plan_min_core:
        step1_cap, step1_at = f.plan_step_1
        step2_cap, step2_at = f.plan_step_2
        plan = step1_cap if T < step1_at else step2_cap if T < step2_at else f.plan_max
        plan = min(plan, core - f.plan_floor)

    work = min(f.work_max, core - plan - f.work_floor)
    cycle_cost = plan + work
    if cycle_cost > 0:
        max_cycles = max(1, int((core - f.work_floor) // cycle_cost))
    else:
        max_cycles = 1

    commit_cap = _clamp(f.commit_frac * T, f.commit_min, f.commit_max)
    commit_floor = max(0.0, core - max_cycles * cycle_cost)
    bash_cap = _clamp(f.bash_frac * T, f.bash_min, f.bash_max)
    finalize = _clamp(f.finalize_frac * T, f.finalize_min, f.finalize_max)

    if token_limit:
        token_budget = int(f.token_fraction * float(token_limit))
    elif f.token_fraction < 1.0:
        token_budget = int(f.token_fraction * f.token_fallback)
    else:
        token_budget = int(f.token_fallback)

    return Budget(
        T=T,
        source=source,
        margin=margin,
        hard=hard,
        reserve=reserve,
        core=core,
        plan=plan,
        work=work,
        max_cycles=max_cycles,
        commit_cap=commit_cap,
        commit_floor=commit_floor,
        bash_cap=bash_cap,
        finalize=finalize,
        request_limit=request_limit,
        token_budget=token_budget,
        token_source=token_source,
        gate_min=margin + f.gate_extra,
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


def extract_token_limit(instruction: str = "") -> tuple[float, str]:
    """Resolve the raw task token limit. Returns (limit, source)."""
    found = _env_float(TOKEN_ENV_CANDIDATES)
    if found is not None:
        return found
    match = _TOKEN_RE.search(instruction or "")
    if match:
        return float(match.group(1).replace(",", "")), "text"
    return float(TOKEN_FALLBACK), "fallback"
