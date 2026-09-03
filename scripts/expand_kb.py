#!/usr/bin/env python3
"""Generate the semantic expansion artifact for the MITRE KB (dev-only).

Issue #94: close the BM25 paraphrase gap (P@5 20% on SOC phrasings vs
100% literal, `research/embeddings/analysis/bm25-baseline.md`) with no
in-zip model. At build time the dev LLM writes 2-3 incident-report-style
paraphrase sentences per technique (709 rows); the output is a PINNED
artifact next to the cheat sheet. The submission never calls an LLM
(the agent runtime is fully offline) — exactly like the pinned cheats,
which are also a dev-time LLM artifact (`build_mitre_kb.py` never calls
an LLM either; regeneration is a scripted event).

The prompt template is version-pinned (`PROMPT_VERSION`); bumping it is
a scripted event (new constant + diff-check of the output), same
discipline as the ATT&CK version pins in `build_mitre_kb.py`.

Usage (dev; needs the LLM endpoint from .env or environment):
    uv run --project cli --no-sync python scripts/expand_kb.py \
        [--kb agent/shlepa_agent/kb] [--out <jsonl>] [--model M] \
        [--parallel 4] [--limit N] [--force]

- Resumable: rows already present in the output file are skipped
  (unless --force), so an interrupted run is re-executed as-is.
- The script appends as it goes (progress survives crashes).
- Exit code 0 only when every requested row is present in the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

#: Pinned prompt version (bump = scripted event; see module docstring).
PROMPT_VERSION = 1

#: Pinned generation date of the artifact (constant so the file is a
#: reproducible pinned input, not "the date this script last ran").
GENERATED = "2026-09-03"

#: Technique-id pattern used to validate generated text (never allowed:
#: the expansion must be indicator language, not identity language).
TID_RE = re.compile(r"T\d{4}(?:\.\d{3})?")

PROMPT_V1 = """\
Write 2-3 short sentences for a security-detection knowledge base.
They must describe, in the style of an incident report, what an analyst
would observe on the victim host when the following technique is
carried out.

Technique: {name}
Detection notes: {cheat}

Rules:
- Describe the attacker's observable actions and artifacts: processes,
  files, services, scheduled jobs, network traffic, registry entries,
  event log entries, accounts, credentials.
- Read like natural SOC incident-report phrasing (e.g. "a scheduled
  task was created that runs a download utility every hour").
- Do NOT use the technique name, its ID, or the word "MITRE".
- Do NOT quote the detection notes verbatim; rephrase and add typical
  concrete variations.
- Plain sentences only, no lists, no markdown.
"""


def prompt_for(version: int, name: str, cheat: str) -> str:
    if version == 1:
        return PROMPT_V1.format(name=name, cheat=cheat)
    raise ValueError(f"unknown prompt version {version}")


# --------------------------------------------------------------------- .env

def load_env_file(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines) into os.environ (no override)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


# ------------------------------------------------------------- LLM request

def chat(client: httpx.Client, model: str, prompt: str,
         max_tokens: int) -> str:
    """One chat completion with bounded retries; raises on final failure.

    The dev endpoint (llama.cpp, Qwen3-class thinking model) otherwise
    spends ``max_tokens`` on reasoning and returns empty content, so the
    Qwen3 thinking toggle is sent via ``chat_template_kwargs``; endpoints
    without the toggle reject it with a 400 and we retry without it.
    """
    base = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }
    last: Exception | None = None
    for attempt in range(3):
        try:
            body = {**base,
                    "chat_template_kwargs": {"enable_thinking": False}}
            resp = client.post("/chat/completions", json=body, timeout=120.0)
            if resp.status_code == 400 and "chat_template_kwargs" in resp.text:
                resp = client.post("/chat/completions", json=base,
                                   timeout=120.0)
            resp.raise_for_status()
            payload = resp.json()
            content = (
                payload.get("choices") or [{}]
            )[0].get("message", {}).get("content", "")
            return (content or "").strip()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            time.sleep(2.0 * (2 ** attempt))
    raise RuntimeError(f"LLM call failed after 3 attempts: {last!r}")


# --------------------------------------------------------------------- main

def existing_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.add(json.loads(line)["id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", type=Path,
                    default=Path("agent/shlepa_agent/kb"))
    ap.add_argument("--out", type=Path, default=None,
                    help="output jsonl (default: <kb>/expansion.jsonl)")
    ap.add_argument("--model", default=None,
                    help="model name (default: LOCAL_AGENT_MODEL)")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N missing rows (smoke runs)")
    ap.add_argument("--force", action="store_true",
                    help="regenerate rows that already exist in the output")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    model = args.model or os.environ.get("LOCAL_AGENT_MODEL")
    if not base_url or not model:
        print("ERROR: OPENAI_BASE_URL and LOCAL_AGENT_MODEL must be set "
              "(.env or environment)", file=sys.stderr)
        return 2

    out = args.out or (args.kb / "expansion.jsonl")
    rows = json.loads((args.kb / "rows.json").read_text(encoding="utf-8"))
    cheats: dict[str, str] = {}
    for line in (args.kb / "cheats.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            cheats[c["id"]] = c["cheat"]

    todo = [
        tid for tid in rows
        if tid in cheats and (args.force or tid not in existing_ids(out))
    ]
    if args.limit:
        todo = todo[:args.limit]
    print(f"rows={len(rows)} todo={len(todo)} out={out} "
          f"prompt_v{PROMPT_VERSION} model={model} parallel={args.parallel}")
    if not todo:
        print("nothing to do")
        return 0

    client = httpx.Client(base_url=base_url.rstrip("/"),
                          headers={"Authorization": f"Bearer {api_key}"})
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    failures: list[str] = []
    tid_warns = 0
    done = 0
    t0 = time.perf_counter()

    def work(tid: str) -> tuple[str, str | None]:
        try:
            text = chat(client, model,
                        prompt_for(PROMPT_VERSION, rows[tid]["name"],
                                   cheats[tid]),
                        max_tokens=160)
        except RuntimeError as exc:
            # Never persist the error text as a row: a failed row must
            # stay "missing" so a re-run fills it (failures go to the
            # summary + stderr via the failures list).
            print(f"  fail {tid}: {exc}", file=sys.stderr, flush=True)
            return tid, None
        return tid, text or None

    try:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {pool.submit(work, tid): tid for tid in todo}
            for fut in as_completed(futs):
                tid, text = fut.result()
                with lock:
                    if text is None:
                        failures.append(tid)
                    else:
                        if TID_RE.search(text):
                            # identity language leaked in: strip the
                            # offending sentence, keep the rest
                            parts = [s for s in re.split(r"(?<=[.!?]) ", text)
                                     if not TID_RE.search(s)]
                            text = " ".join(parts).strip()
                            tid_warns += 1
                        if text:
                            with out.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(
                                    {"id": tid, "v": PROMPT_VERSION,
                                     "text": text},
                                    ensure_ascii=False) + "\n")
                    done += 1
                    if done % 25 == 0 or done == len(todo):
                        el = time.perf_counter() - t0
                        print(f"  {done}/{len(todo)} "
                              f"({el / max(done, 1):.1f}s/row, "
                              f"{done / max(el, 1e-9):.2f} rows/s)",
                              flush=True)
    finally:
        client.close()

    el = time.perf_counter() - t0
    size = out.stat().st_size if out.is_file() else 0
    n_rows = len(existing_ids(out))
    print(f"done in {el:.0f}s; output {n_rows} rows, {size/1024:.1f} KB; "
          f"tid-stripped={tid_warns} failures={len(failures)}")
    if failures:
        print(f"FAILED (re-run to fill): {', '.join(failures[:10])}"
              + (" ..." if len(failures) > 10 else ""), file=sys.stderr)
        return 1
    print(f"artifact pinned: {out} (prompt v{PROMPT_VERSION}, "
          f"generated={GENERATED})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
