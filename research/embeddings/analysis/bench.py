#!/usr/bin/env python3
"""Embedding/benchmark harness for the MITRE KB research (dev-only).

Scores any retrieval method on the shared paraphrase+literal query set
(``queries.jsonl`` next to this file), so BM25 (the current ``mitre_kb``
tool) and every embedding candidate (ONNX model, LLM endpoint, ...) are
measured on identical ground truth.

Metrics: P@1 and P@5 over the live-pattern corpus (a query is a hit when
its #1 — or any top-5 — result is in the query's accepted-id set; old ids
are resolved through the alias map first). Splits: all / paraphrase /
literal.

Usage (from repo root):
    # BM25 baseline (no extra inputs):
    uv run --project cli --no-sync python research/embeddings/analysis/bench.py bm25

    # Vector method: precompute doc vectors once (any embedder) and score:
    uv run --project cli --no-sync python research/embeddings/analysis/bench.py \
        vectors --doc-vectors <tid->vector.json> \
        --query-vectors <qid->vector.json> [--rrf-k 60]

    vectors mode reports the dense P@1/P@5; add --rrf-k to also report
    RRF fusion with BM25 (the hybrid design under study).

Exit code 0 on success; the per-query table goes to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "agent"))

from shlepa_agent.mitre_kb import MitreKB, KB_DIR  # noqa: E402

QUERIES = Path(__file__).with_name("queries.jsonl")


def load_queries() -> list[dict]:
    out = []
    for line in QUERIES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def score(rank: list[str], expected: list[str], kb: MitreKB) -> tuple[bool, bool]:
    """(hit@1, hit@5) for a ranked id list against the accepted set."""
    accepted: set[str] = set()
    for e in expected:
        try:
            accepted.add(kb.resolve_tid(e.upper())[0])
        except KeyError:
            accepted.add(e.upper())
    top1 = rank[:1]
    top5 = rank[:5]
    return any(t in accepted for t in top1), any(t in accepted for t in top5)


def fmt(report: list[dict]) -> str:
    lines: list[str] = []
    for r in report:
        mark = "OK " if r["hit5"] else "MISS"
        t1 = "ok" if r["hit1"] else "--"
        lines.append(
            f"{mark} [{r['type']}] {r['id']:>4} expected={','.join(r['expected'])} "
            f"top5={','.join(r['top5'])}"
        )
        lines.append(f"     q: {r['text']}")
    return "\n".join(lines)


def summarize(
    rows: list[dict], title: str,
) -> None:
    def agg(sub: list[dict]) -> str:
        n = len(sub)
        p1 = sum(r["hit1"] for r in sub) / n * 100
        p5 = sum(r["hit5"] for r in sub) / n * 100
        return f"{n:3d} queries  P@1 {p1:5.1f}%  P@5 {p5:5.1f}%"

    print(f"\n=== {title} ===")
    print(f"all        {agg(rows)}")
    for split in ("paraphrase", "literal"):
        sub = [r for r in rows if r["type"] == split]
        if sub:
            print(f"{split:8s} {agg(sub)}")


def run_bm25(kb: MitreKB, queries: list[dict]) -> list[dict]:
    rows = []
    for q in queries:
        rank = [tid for tid, _ in kb._bm25(q["text"])]
        h1, h5 = score(rank, q["expected"], kb)
        rows.append(
            {
                "qid": q["id"], "id": q["id"], "type": q["type"], "text": q["text"],
                "expected": q["expected"], "top5": rank[:5],
                "hit1": h1, "hit5": h5, "method": "bm25",
            }
        )
    return rows


def run_vectors(
    kb: MitreKB, queries: list[dict],
    doc_vecs: dict[str, list[float]], q_vecs: dict[str, list[float]],
    rrf_k: int | None,
) -> list[dict]:
    tids = list(kb.rows)  # stable corpus order
    rows = []
    for q in queries:
        qv = q_vecs[q["id"]]
        scored = sorted(
            ((tid, cosine(qv, doc_vecs[tid])) for tid in tids if tid in doc_vecs),
            key=lambda p: (-p[1], p[0]),
        )
        dense_rank = [tid for tid, _ in scored]
        h1, h5 = score(dense_rank, q["expected"], kb)
        entry = {
            "qid": q["id"], "id": q["id"], "type": q["type"], "text": q["text"],
            "expected": q["expected"], "top5": dense_rank[:5],
            "hit1": h1, "hit5": h5, "method": "dense",
        }
        rows.append(entry)
        if rrf_k:
            bm = dict((tid, i) for i, (tid, _) in
                      enumerate(kb._bm25(q["text"])))
            fused = {
                tid: 1 / (rrf_k + 1 + bm.get(tid, len(tids)))
                for tid, _ in dense_rank
            }
            for tid, i in bm.items():
                if tid not in fused:
                    fused[tid] = 1 / (rrf_k + 1 + i)
            hybrid_rank = [t for t, _ in sorted(fused.items(), key=lambda p: (-p[1], p[0]))]
            h1h, h5h = score(hybrid_rank, q["expected"], kb)
            rows.append(
                {
                    "qid": q["id"], "id": q["id"] + "+rrf", "type": q["type"],
                    "text": q["text"], "expected": q["expected"],
                    "top5": hybrid_rank[:5], "hit1": h1h, "hit5": h5h,
                    "method": f"rrf_k={rrf_k}",
                }
            )
    return rows


def validate_queries(kb: MitreKB, queries: list[dict]) -> list[str]:
    """Return expected ids that resolve to nothing in the KB (bad ground truth)."""
    bad = []
    for q in queries:
        for e in q["expected"]:
            try:
                kb.resolve_tid(e.upper())
            except KeyError:
                bad.append(f"{q['id']}: {e}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["bm25", "vectors"])
    ap.add_argument("--kb-dir", type=Path, default=KB_DIR)
    ap.add_argument("--doc-vectors", type=Path, help="json: tid -> vector")
    ap.add_argument("--query-vectors", type=Path, help="json: qid -> vector")
    ap.add_argument("--rrf-k", type=int, default=None,
                    help="also report RRF fusion with BM25 (vectors mode)")
    ap.add_argument("--save", type=Path, help="save per-query rows (jsonl)")
    args = ap.parse_args()

    kb = MitreKB(args.kb_dir)
    queries = load_queries()
    bad = validate_queries(kb, queries)
    if bad:
        print("ERROR: expected ids not in KB (fix queries.jsonl):", file=sys.stderr)
        for b in bad:
            print("  ", b, file=sys.stderr)
        sys.exit(2)

    if args.mode == "bm25":
        rows = run_bm25(kb, queries)
        summarize(rows, "BM25 (current mitre_kb scoring, cheat corpus)")
        print("\n" + fmt(rows))
    else:
        if not args.doc_vectors or not args.query_vectors:
            ap.error("--doc-vectors and --query-vectors are required in vectors mode")
        doc_vecs = json.loads(args.doc_vectors.read_text(encoding="utf-8"))
        q_vecs = json.loads(args.query_vectors.read_text(encoding="utf-8"))
        missing = [q["id"] for q in queries if q["id"] not in q_vecs]
        if missing:
            ap.error(f"query vectors missing for: {missing}")
        rows = run_vectors(kb, queries, doc_vecs, q_vecs, args.rrf_k)
        for method in sorted({r["method"] for r in rows}):
            summarize([r for r in rows if r["method"] == method], method)
        print("\n" + fmt([r for r in rows if r["method"] == "dense"]))

    if args.save:
        with args.save.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"\nsaved {len(rows)} rows -> {args.save}")


if __name__ == "__main__":
    main()
