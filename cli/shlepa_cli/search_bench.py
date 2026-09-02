"""Search-engine measurement harness (measure-harness).

Runs the annotated query set (research/code_search/analysis/queries.json)
plus a generated >=10k-file synthetic corpus over the available engines
(read-all baseline, rg, sifs bm25) and emits a CSV + markdown report to
research/code_search/analysis/.

Engines are exercised through the exact agent code path
(shlepa_agent.code_search.code_search) so the measured output is what the
tool returns to the model. Metrics per query:

- hit@1 / hit@3: is the gold file the first / a top-3 ranked result file;
- tokens_to_locate: chars/4 tokens of the result payload up to and
  including the first window that overlaps the gold line range (the cost
  of actually reaching the answer); None when the gold file never appears;
- latency: wall time of the engine call (index rebuild included for sifs,
  which runs --no-cache and is stateless).

The read-all baseline simulates the naive strategy: read every file in
the corpus; cost = total corpus tokens, hit = guaranteed, latency = time
to read all files. It is the upper bound every engine must beat on
tokens-to-locate.

Dev/research tooling only: no agent core changes, no new agent deps.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shlepa_agent import code_search as engine

#: Tool-call parameters for the measured engines (the agent defaults).
LIMIT = 5
MAX_TOKENS = 1500

#: One entry header per line, e.g. "3. routers/auth.py:14-27  (def login)".
ENTRY_RE = re.compile(r"^(\d+)\.\s+(\S+):(\d+)-(\d+)")

#: Synthetic corpus generator identity (reproducibility).
SYNTHETIC_GENERATOR = "shlepa_cli.search_bench.generate_synthetic v1"
SYNTHETIC_SEED = 20260831
SYNTHETIC_TARGET_FILES = 10500

#: The eight planted functions of the synthetic corpus (query -> markers).
#: The generator places each gold function in a seeded-random file.
SYNTHETIC_GOLD_FUNCTIONS: dict[str, str] = {
    "synth-retry-backoff": "compute_retry_backoff",
    "synth-quota-limit": "enforce_quota_limit",
    "synth-token-refresh": "refresh_access_token",
    "synth-ledger-prune": "prune_ledger_entries",
    "synth-schedule-shift": "shift_work_schedule",
    "synth-archive-pack": "pack_archive_batches",
    "synth-rate-shed": "shed_rate_load",
    "synth-rotation-window": "rotation_window_days",
}

#: Natural-language queries for the synthetic gold functions.
SYNTHETIC_QUERIES: dict[str, str] = {
    "synth-retry-backoff": "find the function that computes the retry backoff delay",
    "synth-quota-limit": "where is the quota limit enforced on usage",
    "synth-token-refresh": "find where the access token is refreshed",
    "synth-ledger-prune": "which function prunes old ledger entries",
    "synth-schedule-shift": "find the function that shifts a work schedule",
    "synth-archive-pack": "where are archive batches packed",
    "synth-rate-shed": "find the rate-based load shedding function",
    "synth-rotation-window": "where is the credential rotation window computed",
}


@dataclass
class Query:
    id: str
    corpus: str
    query: str
    gold_file: str
    gold_range: tuple[int, int]
    intent: str
    style: str = "nl"


@dataclass
class EngineResult:
    engine: str
    hit1: bool
    hit3: bool
    tokens_to_locate: int | None
    latency_ms: float
    status: str
    output: str


def _git(repo_root: Path, *args: str) -> str:
    try:
        return (
            subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            .stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def corpus_id_for(root: Path, repo_root: Path) -> str:
    """Stable corpus identifier.

    Last commit that touched the corpus dir (repo corpora); content hash
    of file paths + sizes when the corpus is uncommitted (e.g. new files).
    """
    rel = root.relative_to(repo_root).as_posix()
    sha = _git(repo_root, "log", "-1", "--format=%H", "--", rel)
    if sha:
        return f"git:{sha[:12]}"
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(f"{p.relative_to(root).as_posix()}:{p.stat().st_size}\n".encode())
    return f"content:{h.hexdigest()[:16]}"


def load_queries(path: Path) -> tuple[list[Query], dict]:
    raw = json.loads(path.read_text())
    queries = [
        Query(
            id=q["id"],
            corpus=q["corpus"],
            query=q["query"],
            gold_file=q["gold_file"],
            gold_range=tuple(q["gold_range"]),
            intent=q.get("intent", ""),
            style=q.get("style", "nl"),
        )
        for q in raw["queries"]
    ]
    return queries, raw


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def parse_entries(text: str) -> list[dict]:
    """Split engine output into ranked entry blocks.

    Each block carries the entry header fields plus its raw text (for the
    token count). Truncation/summary markers close the current block.
    """
    entries: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = ENTRY_RE.match(line.strip())
        if m:
            if current:
                entries.append(current)
            current = {
                "rank": int(m.group(1)),
                "file": m.group(2),
                "w0": int(m.group(3)),
                "w1": int(m.group(4)),
                "text": line + "\n",
            }
        elif line.startswith("... [truncated"):
            if current:
                entries.append(current)
                current = None
        elif current is not None:
            current["text"] += line + "\n"
    if current:
        entries.append(current)
    return entries


def _overlaps(entry: dict, gold_range: tuple[int, int]) -> bool:
    gs, ge = gold_range
    return entry["w0"] <= ge and entry["w1"] >= gs


def _same_file(entry_file: str, gold_file: str) -> bool:
    """Compare result file to gold, tolerating absolute paths (rg emits
    absolute paths when the search target is absolute; sifs emits paths
    relative to the search dir)."""
    e = entry_file.replace("\\", "/").rstrip("/")
    g = gold_file.replace("\\", "/")
    return e == g or e.endswith("/" + g)


def evaluate_output(
    output: str, gold_file: str, gold_range: tuple[int, int]
) -> tuple[bool, bool, int | None]:
    """hit@1, hit@3, tokens-to-locate for one engine output."""
    entries = parse_entries(output)
    if not entries:
        return False, False, None
    files = [e["file"] for e in entries]
    hit1 = _same_file(files[0], gold_file)
    hit3 = any(_same_file(f, gold_file) for f in files[:3])
    tokens: int | None = None
    for i, e in enumerate(entries):
        if _same_file(e["file"], gold_file) and _overlaps(e, gold_range):
            prefix = "".join(x["text"] for x in entries[: i + 1])
            tokens = max(1, len(prefix) // engine.CHARS_PER_TOKEN)
            break
    return hit1, hit3, tokens


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def run_engine_query(
    engine_name: str, q: Query, root: Path
) -> EngineResult:
    """Run one annotated query over one engine and evaluate the gold."""
    t0 = time.monotonic()
    if engine_name == "read-all":
        chars = 0
        n_files = 0
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    chars += p.stat().st_size
                    n_files += 1
                except OSError:
                    continue
        latency_ms = (time.monotonic() - t0) * 1000
        return EngineResult(
            engine="read-all",
            hit1=True,
            hit3=True,
            tokens_to_locate=max(1, chars // engine.CHARS_PER_TOKEN),
            latency_ms=latency_ms,
            status=f"read {n_files} file(s)",
            output="",
        )

    output = engine.code_search(
        q.query,
        ".",
        limit=LIMIT,
        max_tokens=MAX_TOKENS,
        workdir=root,
        engine=engine_name,
    )
    latency_ms = (time.monotonic() - t0) * 1000
    if output.startswith("code_search:") and "not found" in output:
        status = "engine-missing"
    elif "no matches" in output:
        status = "no-match"
    elif "timed out" in output:
        status = "timeout"
    else:
        status = "ok"
    hit1, hit3, tokens = evaluate_output(output, q.gold_file, q.gold_range)
    return EngineResult(
        engine=engine_name,
        hit1=hit1,
        hit3=hit3,
        tokens_to_locate=tokens,
        latency_ms=latency_ms,
        status=status,
        output=output,
    )


# ---------------------------------------------------------------------------
# Synthetic corpus generator
# ---------------------------------------------------------------------------

_NOUNS = [
    "ledger", "quota", "token", "schedule", "archive", "rate", "rotation",
    "backoff", "batch", "cache", "queue", "policy", "metric", "report",
    "invoice", "shipment", "invoice", "coupon", "voucher", "refund",
    "tenant", "tenant", "region", "cluster", "node", "probe", "signal",
]
_VERBS = [
    "compute", "enforce", "refresh", "prune", "shift", "pack", "shed",
    "rotate", "flush", "merge", "verify", "emit", "collect", "apply",
    "derive", "clamp", "normalize", "aggregate", "dispatch", "snapshot",
]


def _module_lines(rng: random.Random, idx: int) -> list[str]:
    """One plausible module: docstring, imports, 3-6 functions/classes."""
    noun = _NOUNS[rng.randrange(len(_NOUNS))]
    verb = _VERBS[rng.randrange(len(_VERBS))]
    module = f"{noun}_service_{idx}"
    lines: list[str] = [
        f'"""{module}: {verb} the {noun} domain (synthetic corpus)."""',
        "",
        "import logging",
        "from dataclasses import dataclass",
        "",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        f"MAX_{noun.upper()}_ITEMS = {rng.randint(64, 4096)}",
        "",
        "",
        "@dataclass",
        f"class {noun.title()}Record:",
        "    id: int",
        "    payload: str",
        "    score: float = 0.0",
        "",
    ]
    for f_i in range(rng.randint(3, 6)):
        fname = f"{_VERBS[rng.randrange(len(_VERBS))]}_{_NOUNS[rng.randrange(len(_NOUNS))]}_{f_i}"
        nlines = rng.randint(6, 14)
        lines.append(f"def {fname}(record: {noun.title()}Record, limit: int = 0) -> float:")
        lines.append(f'    """Handle the {noun} case {f_i}."""')
        lines.append("    total = 0.0")
        for _ in range(nlines):
            op = rng.choice([
                "total += record.score",
                "total += 1.0",
                "record.score = clamp(record.score, 0.0, 1.0)",
                "if total > limit and limit:",
                "    break",
                "logger.debug('%s: %s', __name__, record.id)",
                "record.payload = record.payload[:128]",
            ])
            lines.append(op)
        lines.append("    return total")
        lines.append("")
    lines.append("def clamp(value: float, lo: float, hi: float) -> float:")
    lines.append("    return max(lo, min(hi, value))")
    lines.append("")
    return lines


def generate_synthetic(root: Path, seed: int, target_files: int) -> list[Query]:
    """Generate a seeded Python monorepo of ~target_files modules.

    Plants SYNTHETIC_GOLD_FUNCTIONS into seeded-random files and returns
    the matching annotated queries. Deterministic for a fixed seed.
    """
    rng = random.Random(seed)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    # Package tree: pkg_<i>/mod_<j>.py
    per_pkg = 8
    n_pkgs = target_files // per_pkg
    file_paths: list[Path] = []
    for i in range(n_pkgs):
        pkg = root / f"pkg_{i:04d}"
        pkg.mkdir(parents=True, exist_ok=True)
        for j in range(per_pkg):
            file_paths.append(pkg / f"mod_{j}.py")

    # Plant gold functions in distinct seeded-random files (no collisions).
    INSERT_AT = 6  # 0-based line index of the insertion point
    GOLD_RANGE = (INSERT_AT + 1, INSERT_AT + 6)  # 1-based def..return lines
    used_slots: set[int] = set()
    gold_files: dict[str, Path] = {}
    gold_by_slot: dict[int, str] = {}
    for key in SYNTHETIC_GOLD_FUNCTIONS:
        slot = rng.randrange(len(file_paths))
        while slot in used_slots:  # deterministic collision retry
            slot = rng.randrange(len(file_paths))
        used_slots.add(slot)
        gold_files[key] = file_paths[slot]
        gold_by_slot[slot] = key

    for idx, path in enumerate(file_paths):
        lines = _module_lines(rng, idx)
        key = gold_by_slot.get(idx)
        if key:
            fname = SYNTHETIC_GOLD_FUNCTIONS[key]
            lines[INSERT_AT:INSERT_AT] = [
                f"def {fname}(ctx: dict) -> int:",
                f'    """{SYNTHETIC_QUERIES[key].title().rstrip(".")}."""',
                "    base = int(ctx.get('base', 1))",
                "    cap = int(ctx.get('cap', 64))",
                "    return min(cap, base * 2)",
                "",
            ]
        path.write_text("\n".join(lines))

    queries: list[Query] = []
    for key, fname in SYNTHETIC_GOLD_FUNCTIONS.items():
        rel = gold_files[key].relative_to(root).as_posix()
        # NL phrasing (sifs domain) + the bare identifier (rg domain).
        queries.append(
            Query(
                id=key,
                corpus="synthetic-10k",
                query=SYNTHETIC_QUERIES[key],
                gold_file=rel,
                gold_range=GOLD_RANGE,
                intent="navigate",
                style="nl",
            )
        )
        queries.append(
            Query(
                id=f"{key}-kw",
                corpus="synthetic-10k",
                query=fname,
                gold_file=rel,
                gold_range=GOLD_RANGE,
                intent="navigate",
                style="keyword",
            )
        )
    return queries


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def sifs_provenance(repo_root: Path) -> dict:
    prov = repo_root / "agent" / "tools" / "bin" / "PROVENANCE.md"
    info = {"version": engine.SIFS_PINNED_VERSION, "sha256": ""}
    try:
        text = prov.read_text()
        m = re.search(r"(?:sha256|SHA256)[^0-9a-f]*([0-9a-f]{64})", text)
        if m:
            info["sha256"] = m.group(1)
    except OSError:
        pass
    return info


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def write_report(
    out_dir: Path,
    rows: list[dict],
    corpus_meta: list[dict],
    prov: dict,
    repo_sha: str,
) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    csv_path = out_dir / f"search_bench_{stamp}.csv"
    md_path = out_dir / f"search_bench_{stamp}.md"

    cols = [
        "family", "corpus", "engine", "query_id", "intent", "style",
        "hit1", "hit3", "tokens_to_locate", "latency_ms", "status",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})

    families = sorted({r["family"] for r in rows})
    engines = ["read-all", "rg", "sifs"]
    lines: list[str] = [
        "# Search-engine measurement report",
        "",
        f"- generated: {stamp}Z ({SYNTHETIC_GENERATOR})",
        f"- repo sha: {repo_sha or 'unknown'}",
        f"- sifs: v{prov['version']}"
        + (f" sha256 {prov['sha256'][:16]}…" if prov["sha256"] else " (no provenance sha)"),
        f"- engine params: limit={LIMIT}, max_tokens={MAX_TOKENS}, "
        "sifs --offline --no-cache (per-call index rebuild)",
        "- tokens: chars/4 estimate (repo convention); "
        "tokens_to_locate counts the payload up to the first window overlapping the gold range",
        "- read-all = naive baseline (read every file; hit guaranteed)",
        "",
        "## Corpora",
        "",
        "| corpus | family | kind | files | tokens (read-all) | corpus id |",
        "|--------|--------|------|-------|-------------------|-----------|",
    ]
    for c in corpus_meta:
        lines.append(
            f"| {c['id']} | {c['family']} | {c['kind']} | {c['files']} "
            f"| {c['tokens']} | {c['corpus_id']} |"
        )
    styles = sorted({r.get("style") or "nl" for r in rows})
    lines += ["", "## Per-family summary (mean over queries)", ""]
    lines.append(
        "| family | style | engine | queries | hit@1 | hit@3 "
        "| tokens-to-locate (hits) | latency ms |"
    )
    lines.append(
        "|--------|-------|--------|---------|-------|-------"
        "|-------------------------|------------|"
    )
    for fam in families:
        for sty in styles:
            for eng in engines:
                sub = [
                    r for r in rows
                    if r["family"] == fam and (r.get("style") or "nl") == sty
                    and r["engine"] == eng
                ]
                if not sub:
                    continue
                toks = [r["tokens_to_locate"] for r in sub if r["tokens_to_locate"]]
                lines.append(
                    f"| {fam} | {sty} | {eng} | {len(sub)} "
                    f"| {_mean([1.0 if r['hit1'] else 0.0 for r in sub]):.2f} "
                    f"| {_mean([1.0 if r['hit3'] else 0.0 for r in sub]):.2f} "
                    f"| {_mean(toks):.0f} "
                    f"| {_mean([r['latency_ms'] for r in sub]):.0f} |"
                )
    lines += ["", "## Per-corpus detail", ""]
    for c in corpus_meta:
        sub = [r for r in rows if r["corpus"] == c["id"]]
        if not sub:
            continue
        lines.append(f"### {c['id']} ({c['family']})")
        lines.append("")
        lines.append("| engine | queries | hit@1 | hit@3 | tokens-to-locate (hits) | latency ms |")
        lines.append("|--------|---------|-------|-------|-------------------------|------------|")
        for eng in engines:
            eng_rows = [r for r in sub if r["engine"] == eng]
            if not eng_rows:
                continue
            toks = [r["tokens_to_locate"] for r in eng_rows if r["tokens_to_locate"]]
            lines.append(
                f"| {eng} | {len(eng_rows)} "
                f"| {_mean([1.0 if r['hit1'] else 0.0 for r in eng_rows]):.2f} "
                f"| {_mean([1.0 if r['hit3'] else 0.0 for r in eng_rows]):.2f} "
                f"| {_mean(toks):.0f} "
                f"| {_mean([r['latency_ms'] for r in eng_rows]):.0f} |"
            )
        lines.append("")
    lines += [
        "## Notes",
        "",
        "- read-all latency is dominated by file open/read syscalls; it is a",
        "  cost proxy for the naive strategy, not an LLM tool-call simulation.",
        "- sifs latency includes the per-call index rebuild (--no-cache).",
        "- hit@1/hit@3 compare the gold file against ranked result files.",
        "  A hit with tokens_to_locate=None means the gold file appeared",
        "  but no returned window overlapped the gold line range.",
        "",
    ]
    md_path.write_text("\n".join(lines))
    return csv_path, md_path


def run_bench(
    repo_root: Path,
    out_dir: Path,
    queries_file: Path,
    families: list[str] | None = None,
    engines: list[str] | None = None,
    synthetic_files: int = SYNTHETIC_TARGET_FILES,
    synthetic_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Run the full bench; returns (csv_path, md_path)."""
    engines = engines or ["read-all", "rg", "sifs"]
    out_dir.mkdir(parents=True, exist_ok=True)
    queries, raw = load_queries(queries_file)
    corpora = {c["id"]: c for c in raw["corpora"]}
    if families:
        keep = {q.corpus for q in queries if corpora[q.corpus]["family"] in families}
        queries = [q for q in queries if q.corpus in keep]

    corpus_meta: list[dict] = []
    rows: list[dict] = []

    for cid, corp in corpora.items():
        if corp["kind"] == "generated":
            if synthetic_files <= 0:
                continue
            root = synthetic_dir or (
                repo_root / "tmp" / "search-bench" / f"synthetic-{SYNTHETIC_SEED}"
            )
            # Generated corpora carry no queries in queries.json; the
            # generator emits them (NL + keyword) at run time.
            queries = [q for q in queries if q.corpus != cid]
            queries.extend(generate_synthetic(root, SYNTHETIC_SEED, synthetic_files))
            q_in_corpus = [q for q in queries if q.corpus == cid]
            if families and corp["family"] not in families:
                continue
            n_files = sum(1 for p in root.rglob("*") if p.is_file())
            corpus_meta.append(
                {
                    "id": cid,
                    "family": corp["family"],
                    "kind": f"generated ({SYNTHETIC_GENERATOR}, seed={SYNTHETIC_SEED})",
                    "files": n_files,
                    "tokens": 0,  # filled below by read-all
                    "corpus_id": f"seed:{SYNTHETIC_SEED} generator:{SYNTHETIC_GENERATOR}",
                }
            )
        else:
            q_in_corpus = [q for q in queries if q.corpus == cid]
            if not q_in_corpus:
                continue
            root = repo_root / corp["root"]
            n_files = sum(1 for p in root.rglob("*") if p.is_file())
            corpus_meta.append(
                {
                    "id": cid,
                    "family": corp["family"],
                    "kind": corp["kind"],
                    "files": n_files,
                    "tokens": 0,
                    "corpus_id": corpus_id_for(root, repo_root),
                }
            )
        for q in q_in_corpus:
            for eng in engines:
                res = run_engine_query(eng, q, root)
                rows.append(
                    {
                        "family": corp["family"],
                        "corpus": cid,
                        "engine": eng,
                        "query_id": q.id,
                        "intent": q.intent,
                        "style": q.style,
                        "hit1": res.hit1,
                        "hit3": res.hit3,
                        "tokens_to_locate": res.tokens_to_locate,
                        "latency_ms": round(res.latency_ms, 1),
                        "status": res.status,
                    }
                )
                if eng == "read-all" and res.tokens_to_locate:
                    for c in corpus_meta:
                        if c["id"] == cid:
                            c["tokens"] = res.tokens_to_locate

    repo_sha = _git(repo_root, "rev-parse", "HEAD")
    return write_report(out_dir, rows, corpus_meta, sifs_provenance(repo_root), repo_sha)


def main(
    families: str = "",
    engines: str = "read-all,rg,sifs",
    out: str = "",
    synthetic_files: int = SYNTHETIC_TARGET_FILES,
) -> int:
    from shlepa_cli.config import get_settings

    settings = get_settings()
    repo_root = settings.repo_root
    queries_file = repo_root / "research" / "code_search" / "analysis" / "queries.json"
    out_dir = Path(out) if out else repo_root / "research" / "code_search" / "analysis"
    fams = [f.strip() for f in families.split(",") if f.strip()] or None
    engs = [e.strip() for e in engines.split(",") if e.strip()] or None
    csv_path, md_path = run_bench(
        repo_root,
        out_dir,
        queries_file,
        families=fams,
        engines=engs,
        synthetic_files=synthetic_files,
    )
    print(f"csv: {csv_path}")
    print(f"report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
