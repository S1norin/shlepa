#!/usr/bin/env python3
"""Encode the MITRE KB + query set with VTXAI/vtx-embed models (dev-only).

Prepares the dense side of the C' experiment (see
`research/embeddings/notes/vtx-embed.md` and `analysis/fit-matrix.md`):

1. loads the model weights WITHOUT the `safetensors` package (the format
   is a JSON header + raw tensor bytes; both the dev venv and the ACP
   image lack the library),
2. fits the SIF IDF weights + PC-1 direction on the KB corpus
   (corpus-adaptive, per the reference engine),
3. encodes the 709 doc texts and the 48 bench queries,
4. writes the two vectors files that `bench.py vectors` consumes, plus a
   latency report.

Reference engine (MIT): https://huggingface.co/VTXAI/vtx-embed-7M
(`vortex_embed_v4_5.py` — dequantize/SIF/PC logic adapted verbatim).

Usage (repo root; models downloaded to tmp/vtx-embed/{mini,nano}/):
    uv run --project cli --no-sync python research/embeddings/analysis/vtx_bench.py \
        --model-dir tmp/vtx-embed/nano --out-prefix research/embeddings/analysis/vtx-nano
    # then:
    uv run --project cli --no-sync python research/embeddings/analysis/bench.py \
        vectors --doc-vectors research/embeddings/analysis/vtx-nano-docs.json \
        --query-vectors research/embeddings/analysis/vtx-nano-queries.json \
        --rrf-k 60 --save research/embeddings/analysis/vtx-nano-rows.jsonl

The same script runs unmodified inside the ACP image (numpy + tokenizers
only), so the dev numbers are the ACP numbers:
    docker run --rm \
        -v "$PWD/tmp/vtx-embed/nano:/model" -v "$PWD/research/embeddings/analysis:/bench" \
        -v "$PWD/agent:/agent:ro" --entrypoint /app/.venv/bin/python \
        secureintelligent/acp:latest /bench/vtx_bench.py --model-dir /model \
        --kb-dir /agent/shlepa_agent/kb --out-prefix /bench/vtx-nano-acp
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "agent"))

from shlepa_agent.mitre_kb import MitreKB, KB_DIR  # noqa: E402

QUERIES = Path(__file__).with_name("queries.jsonl")

# ---------------------------------------------------------------- safetensors

_DTYPES = {
    "F64": "<f8", "F32": "<f4", "F16": "<f2", "U8": "u1", "I8": "i1",
    "U32": "<u4", "I32": "<i4", "U64": "<u8", "I64": "<i8", "BOOL": "?",
}


def load_safetensors(path: Path) -> dict[str, np.ndarray]:
    """Minimal safetensors reader (header + raw bytes); no deps."""
    raw = path.read_bytes()
    (hlen,) = struct.unpack_from("<Q", raw, 0)
    header = json.loads(raw[8:8 + hlen])
    out: dict[str, np.ndarray] = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        lo, hi = meta["data_offsets"]
        buf = raw[8 + hlen + lo:8 + hlen + hi]
        out[name] = np.frombuffer(buf, dtype=_DTYPES[meta["dtype"]]).reshape(meta["shape"])
    return out


# ------------------------------------------------- vtx-embed (MIT, adapted)

class VtxEmbed:
    """LF4 4-bit static embedding table + SIF pooling + PC-1 removal."""

    def __init__(self, tensors: dict, tokenizer_path: Path):
        self.packed = np.ascontiguousarray(tensors["embedding_packed"], dtype=np.uint8)
        self.scales = tensors["embedding_scales"].astype(np.float16)
        self.zeros = tensors["embedding_zeros"].astype(np.float16)
        self.dim = self.packed.shape[1] * 2  # two 4-bit values per byte
        self.num_blocks = self.scales.shape[1]
        self.block_size = (self.dim // self.num_blocks) if self.num_blocks else self.dim
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.vocab_size = self.packed.shape[0]
        self.sif_a = 0.05
        self.sif_weights: np.ndarray | None = None
        self.pc_direction: np.ndarray | None = None

    def _dequantize(self, ids: np.ndarray) -> np.ndarray:
        p = self.packed[ids]
        s = self.scales[ids].astype(np.float32)[:, :, None]
        z = self.zeros[ids].astype(np.float32)[:, :, None]
        low = (p & 0x0F).astype(np.float32)
        high = ((p >> 4) & 0x0F).astype(np.float32)
        n = p.shape[0]
        padded = p.shape[1] * 2
        unpacked = np.empty((n, padded), dtype=np.float32)
        unpacked[:, 0::2] = low
        unpacked[:, 1::2] = high
        blocked = unpacked.reshape(n, self.num_blocks, self.block_size)
        out = (blocked * s + z).reshape(n, padded)
        return out[:, : self.dim]

    def tokenize(self, texts: list[str]) -> list[list[int]]:
        enc = self.tokenizer.encode_batch(texts)
        return [[t for t in e.ids if 0 <= t < self.vocab_size] for e in enc]

    def fit_idf(self, token_lists: list[list[int]]) -> None:
        flat = np.concatenate(token_lists) if token_lists else np.empty(0, dtype=np.int64)
        total = max(int(flat.size), 1)
        counts = np.bincount(flat, minlength=self.vocab_size).astype(np.float64)
        p = counts / total
        denom = self.sif_a + p
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where(p > 0, self.sif_a / denom, 1.0)
        self.sif_weights = w.astype(np.float32)

    def encode(self, texts: list[str], fit_pc: bool = False,
               truncate_dim: int | None = None) -> np.ndarray:
        token_lists = self.tokenize(texts)
        n = len(texts)
        flat = np.concatenate(token_lists) if token_lists and any(token_lists) else np.empty(0, dtype=np.int64)
        if flat.size == 0:
            return np.zeros((n, self.dim), dtype=np.float32)
        uniq, inv = np.unique(flat, return_inverse=True)
        uniq_embs = self._dequantize(uniq)
        tok_embs = uniq_embs[inv]
        if self.sif_weights is not None:
            tok_embs = tok_embs * self.sif_weights[flat].astype(np.float32)[:, None]
        ends = np.cumsum([len(t) for t in token_lists])
        starts = np.concatenate([np.zeros(1, dtype=np.int64), ends[:-1]])
        sums = np.add.reduceat(tok_embs, starts, axis=0)
        if self.sif_weights is not None:
            wsum = np.add.reduceat(self.sif_weights[flat].astype(np.float32), starts)
        else:
            wsum = np.maximum(np.array([len(t) for t in token_lists], dtype=np.float32), 1.0)
        embs = sums / np.maximum(wsum, 1e-12)[:, None]
        if fit_pc:
            x = embs - embs.mean(axis=0, keepdims=True)
            _, _, vt = np.linalg.svd(x, full_matrices=False)
            self.pc_direction = vt[0] / (np.linalg.norm(vt[0]) + 1e-12)
        if self.pc_direction is not None:
            embs = embs - (embs @ self.pc_direction)[:, None] * self.pc_direction[None, :]
        if truncate_dim and 0 < truncate_dim < self.dim:
            embs = embs[:, :truncate_dim]
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        return np.divide(embs, np.maximum(norms, 1e-12), out=embs)


# --------------------------------------------------------------------- main

def doc_texts(kb: MitreKB, source: str) -> dict[str, str]:
    """Doc texts. ``bm25`` reproduces the indexed corpus exactly (name
    weighted twice) so the dense results are directly comparable with the
    BM25 baseline."""
    rows = kb.rows
    cheats = kb.cheats
    out = {}
    for tid in rows:
        row = rows[tid]
        name = row["name"]
        cheat = cheats.get(tid, "")
        if source == "bm25":
            out[tid] = f"{tid} {name} {name} {cheat}"
        elif source == "description":
            out[tid] = f"{tid} {name}. {row.get('description', '')}"
        else:  # both
            out[tid] = f"{tid} {name}. {cheat} {row.get('description', '')}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, required=True,
                    help="dir with model.safetensors + tokenizer.json")
    ap.add_argument("--kb-dir", type=Path, default=KB_DIR)
    ap.add_argument("--doc-source", choices=["bm25", "description", "both"], default="bm25")
    ap.add_argument("--truncate-dim", type=int, default=None,
                    help="Matryoshka truncation (default: native dim)")
    ap.add_argument("--out-prefix", type=Path, default=Path("vtx"))
    args = ap.parse_args()

    tensors = load_safetensors(args.model_dir / "model.safetensors")
    model = VtxEmbed(tensors, args.model_dir / "tokenizer.json")
    print(f"model: {args.model_dir}  dims={model.dim}  vocab={model.vocab_size} "
          f"weights_mb={(model.packed.nbytes + model.scales.nbytes + model.zeros.nbytes) / 1e6:.2f}")

    kb = MitreKB(args.kb_dir)
    docs = doc_texts(kb, args.doc_source)
    tids = list(docs)

    # corpus-adaptive SIF + PC fit (same as the reference engine)
    t0 = time.perf_counter()
    model.fit_idf(model.tokenize([docs[t] for t in tids]))
    doc_vecs = model.encode([docs[t] for t in tids], fit_pc=True,
                            truncate_dim=args.truncate_dim)
    fit_sec = time.perf_counter() - t0

    doc_json = {t: doc_vecs[i].astype(np.float32).round(6).tolist() for i, t in enumerate(tids)}
    args.out_prefix.with_name(args.out_prefix.name + "-docs.json").write_text(
        json.dumps(doc_json), encoding="utf-8")

    queries = [json.loads(l) for l in QUERIES.read_text(encoding="utf-8").splitlines() if l.strip()]
    qtexts = [q["text"] for q in queries]
    t0 = time.perf_counter()
    q_vecs = model.encode(qtexts, truncate_dim=args.truncate_dim)
    enc_sec = time.perf_counter() - t0
    q_json = {q["id"]: v.astype(np.float32).round(6).tolist() for q, v in zip(queries, q_vecs)}
    args.out_prefix.with_name(args.out_prefix.name + "-queries.json").write_text(
        json.dumps(q_json), encoding="utf-8")

    print(f"docs={len(tids)} dim={doc_vecs.shape[1]} fit+encode_docs={fit_sec:.2f}s "
          f"queries={len(queries)} encode_queries={enc_sec:.3f}s "
          f"({enc_sec / len(queries) * 1000:.2f} ms/query)")
    print(f"wrote {args.out_prefix.stem}-docs.json / {args.out_prefix.stem}-queries.json")


if __name__ == "__main__":
    main()
