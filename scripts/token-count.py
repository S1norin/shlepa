#!/usr/bin/env python3
"""Token counting for offline KB sizing (dev-only, stdlib only).

Method: posts the text to the dev llama-server /tokenize endpoint
(native, not OpenAI-compatible), so counts match the tokenizer the
agent's model actually uses. Falls back to a ~4 chars/token heuristic
if the endpoint is unreachable.

Usage:
  scripts/token-count.py FILE [FILE ...]
  cat some.txt | scripts/token-count.py -

Reads OPENAI_BASE_URL / OPENAI_API_KEY from the repo-root .env
(falls back to environment variables, then localhost:11434).
"""

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    env = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    env = {**load_env(), **os.environ}
    base = (env.get("OPENAI_BASE_URL") or "http://localhost:11434").rstrip("/")
    # llama-server native endpoints live at the root, not under /v1
    base = base.removesuffix("/v1")
    key = env.get("OPENAI_API_KEY") or "none"
    url = f"{base}/tokenize"

    rc = 0
    for arg in sys.argv[1:]:
        if arg == "-":
            text, label = sys.stdin.read(), "<stdin>"
        else:
            try:
                with open(arg, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError as e:
                print(f"{arg}: unreadable ({e})", file=sys.stderr)
                rc = 1
                continue
            label = arg

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps({"content": text}).encode(),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                tokens = json.loads(resp.read())["tokens"]
            print(f"{label}: {len(tokens)} tokens "
                  f"(llama-server /tokenize at {base})")
        except Exception as e:  # noqa: BLE001 - any endpoint failure falls back
            approx = max(1, len(text) // 4)
            print(f"{label}: ~{approx} tokens "
                  f"(heuristic ~4 chars/token; endpoint failed: {e})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
