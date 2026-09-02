"""log_triage engine: compact, deterministic triage of log evidence files.

Read-only by construction: files are opened in read mode only; the function
never writes, deletes, or executes anything. The output is a compact
plain-text summary (capped by ``max_output`` chars) that replaces many
grep/read round trips on structured-text evidence: SOC JSONL logs, syslog,
web-server logs, application logs, console logs.

Design rules (see research/notes/readonly-tools.md, "deterministic engine +
LLM interpretation"):

- No schema required. JSONL files are detected per file and their key names
  are matched against entity heuristics (user / host / ip / event / process);
  plain-text lines fall back to timestamp + IP + token extraction.
- Deterministic: same input, same output (counters keep first-seen order;
  no randomness, no timestamps of our own).
- Signals, not verdicts: the summary lists candidates (entities, rare
  single-occurrence values, hour spikes); the LLM reasons about them.
- Pure stdlib (json, re, collections, pathlib) — zero new dependencies,
  runs offline inside the ACP image.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

#: Cap on chars the tool result may occupy (fits the v5 regime: the result
#: must be one small context window, not a file dump).
DEFAULT_MAX_OUTPUT = 3500

#: Per-file safety caps (streaming read; larger files are skipped with a note).
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINES_PER_FILE = 500_000

#: Directory triage: file extensions considered evidence, and the file cap.
EVIDENCE_EXTENSIONS = {".jsonl", ".ndjson", ".log", ".txt", ".csv", ".tsv"}
MAX_FILES = 8

# -- per-line extraction ---------------------------------------------------

#: ISO-ish timestamps: 2026-04-17T08:00:00 / 2026-04-17 08:00:00 / 2026/04/17 08:00:00
_TS_RE = re.compile(r"\b(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)")

#: IPv4 (whole tokens only, octets 0-255).
_IP_RE = re.compile(
    r"(?<![0-9.])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?![0-9.])"
)

#: Log severity levels (word-bounded, case-insensitive).
_SEV_RE = re.compile(r"\b(DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|CRIT(?:ICAL)?|FATAL)\b", re.IGNORECASE)

#: Token extraction for plain-text lines (candidate entities / phrases).
#: Leading "/" allowed so URL paths survive ("/api/login").
_TOKEN_RE = re.compile(r"[/A-Za-z0-9][A-Za-z0-9_./:@=-]{2,63}")

_STOPWORDS = frozenset(
    """
    a an and are as at be but by for from has have in is it its of on or that the to was were with
    true false null none yes no not this that then than when while if else
    http https www com net org
    info notice debug warning error critical fatal
    """.split()
)

# -- entity key heuristics (JSONL / JSON lines) -----------------------------

_USER_KEYS = (
    "user", "username", "user_name", "useraccount", "subjectusername",
    "logonaccount", "targetusername", "account", "caller", "actor", "owner",
    "client", "remoteuser", "uid", "login",
)
_HOST_KEYS = (
    "host", "hostname", "machine", "computer", "source", "src", "srcip",
    "server", "workstation", "node", "instance", "computername", "device",
)
_EVENT_KEYS = (
    "eventid", "event_id", "event", "eventname", "eventtype", "op", "action",
    "opcode", "command", "syscall", "category", "level",
)
_PROC_KEYS = (
    "image", "process", "processname", "proc", "exe", "parent", "parentimage",
    "program", "cmd", "cmdline", "commandline", "binary", "executable",
    "path",
)

#: Longest key first so "subjectusername" wins over "user".
_KEY_MATCH = {
    "user": tuple(sorted((k for k in _USER_KEYS), key=len, reverse=True)),
    "host": tuple(sorted((k for k in _HOST_KEYS), key=len, reverse=True)),
    "event": tuple(sorted((k for k in _EVENT_KEYS), key=len, reverse=True)),
    "process": tuple(sorted((k for k in _PROC_KEYS), key=len, reverse=True)),
}


def _entity_value(v: object) -> str | None:
    """Coerce a JSON field value to an entity string (None = skip)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        return v or None
    if isinstance(v, (int, float)):
        return str(v)
    return None


def _is_private_ip(ip: str) -> bool:
    a, b = ip.split(".")[:2]
    a, b = int(a), int(b)
    return a == 10 or a == 127 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


class _FileStats:
    __slots__ = (
        "name", "n_lines", "n_bytes", "kind", "keys", "truncated",
        "t_min", "t_max", "hours", "ips", "sevs", "ents", "first_seen",
    )

    def __init__(self, name: str, n_bytes: int) -> None:
        self.name = name
        self.n_lines = 0
        self.n_bytes = n_bytes
        self.kind = "text"
        self.keys: set[str] = set()
        self.truncated = False
        self.t_min: str | None = None
        self.t_max: str | None = None
        self.hours: Counter[str] = Counter()
        self.ips: Counter[str] = Counter()
        self.sevs: Counter[str] = Counter()
        # category -> Counter of values ("token" is used for plain-text files)
        self.ents: dict[str, Counter[str]] = {
            c: Counter() for c in ("user", "host", "event", "process", "token")
        }
        # category -> first-seen value order (for the rare-once list)
        self.first_seen: dict[str, list[str]] = {
            c: [] for c in ("user", "host", "event", "process", "token")
        }

    def record(self, line: str, record: dict | None) -> None:
        self.n_lines += 1
        m = _TS_RE.search(line)
        if m:
            t = m.group(1)
            if self.t_min is None or t < self.t_min:
                self.t_min = t
            if self.t_max is None or t > self.t_max:
                self.t_max = t
            self.hours[t[:13]] += 1  # YYYY-MM-DDTHH bucket
        for ip in _IP_RE.findall(line):
            self.ips[ip] += 1
        for sev in _SEV_RE.findall(line):
            self.sevs[sev.upper()] += 1
        if record is not None:
            # case-insensitive key match (EventID vs eventid, SubjectUserName...)
            low = {k.lower(): v for k, v in record.items() if isinstance(k, str)}
            for cat, keys in _KEY_MATCH.items():
                for k in keys:
                    if k in low:
                        v = _entity_value(low[k])
                        if v is not None:
                            c = self.ents[cat]
                            if c[v] == 0:
                                self.first_seen[cat].append(v)
                            c[v] += 1
                        break  # one key per category per record
        if record is None:
            for tok in _TOKEN_RE.findall(line):
                if tok.lower() in _STOPWORDS:
                    continue
                c = self.ents["token"]
                if c[tok] == 0:
                    self.first_seen.setdefault("token", []).append(tok)
                c[tok] += 1


def _triage_file(path: Path) -> _FileStats | str:
    """Triage one file; returns stats, or a skip-note string."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return f"== {path.name}: unreadable ({e})"
    if size > MAX_FILE_BYTES:
        return f"== {path.name}: skipped ({size / 1048576:.0f} MB > {MAX_FILE_BYTES // 1048576} MB cap)"
    st = _FileStats(path.name, size)
    jsonl = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            # sniff: is this JSON lines?
            for _ in range(20):
                line = f.readline()
                if not line.strip():
                    continue
                if line.lstrip()[:1] == "{":
                    try:
                        json.loads(line)
                        jsonl = True
                    except (json.JSONDecodeError, ValueError):
                        pass
                break
            f.seek(0)
            st.kind = "jsonl" if jsonl else "text"
            for line in f:
                if st.n_lines >= MAX_LINES_PER_FILE:
                    st.truncated = True
                    break
                record = None
                if jsonl:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        record = json.loads(s)
                    except (json.JSONDecodeError, ValueError):
                        record = None
                    if isinstance(record, dict):
                        st.keys.update(record.keys())
                if line.strip():
                    st.record(line, record if isinstance(record, dict) else None)
    except OSError as e:
        return f"== {path.name}: unreadable ({e})"
    return st


def _fmt_top(counter: Counter[str], n: int) -> str:
    return " ".join(f"{v} ({c})" for v, c in counter.most_common(n))


def _fmt_rare(st: _FileStats, n: int = 10) -> list[str]:
    """Single-occurrence entity values (IOC candidates), first-seen order."""
    out: list[str] = []
    for cat in ("user", "host", "process", "event"):
        cnt = st.ents[cat]
        for v in st.first_seen[cat]:
            if len(out) >= n:
                return out
            if cnt.get(v) == 1:
                out.append(f"{cat}={v}")
    return out


def _fmt_file(st: _FileStats) -> list[str]:
    lines = [f"== {st.name} ({st.n_lines:,} rec, {st.kind}, {st.n_bytes / 1024:.0f} KB)"]
    if st.truncated:
        lines.append(f"   NOTE: capped at {MAX_LINES_PER_FILE:,} lines")
    if st.t_min and st.t_max:
        lines.append(f"   time: {st.t_min} .. {st.t_max}")
    if st.kind == "jsonl" and st.keys:
        keys = ", ".join(sorted(st.keys))
        if len(keys) > 200:
            keys = keys[:200] + "…"
        lines.append(f"   keys: {keys}")
    for cat, label in (("event", "events"), ("user", "users"), ("host", "hosts"), ("process", "procs")):
        top = _fmt_top(st.ents[cat], 8)
        if top:
            lines.append(f"   {label}: {top}")
    if st.ips:
        ext = " [ext] " + " ".join(
            f"{ip} ({c})" for ip, c in st.ips.most_common(8) if not _is_private_ip(ip)
        )
        lines.append(f"   ips: {_fmt_top(st.ips, 8)}{ext}")
    if st.sevs:
        lines.append(f"   levels: {_fmt_top(st.sevs, 6)}")
    if st.kind == "text":
        top = _fmt_top(st.ents["token"], 12)
        if top:
            lines.append(f"   top tokens: {top}")
    rare = _fmt_rare(st)
    if rare:
        lines.append(f"   rare (seen once): {', '.join(rare[:10])}")
    if st.hours and len(st.hours) >= 4:
        counts = sorted(st.hours.values())
        median = counts[len(counts) // 2]
        peak_h, peak_c = st.hours.most_common(1)[0]
        note = f" ≈ {peak_c // max(median, 1)}× median" if median and peak_c > 3 * median else ""
        lines.append(f"   hours: peak {peak_h[:13]}:00 ({peak_c:,} rec){note}")
    return lines


def log_triage(path: str, workdir: Path, max_output: int = DEFAULT_MAX_OUTPUT) -> str:
    """Triage one log/evidence path; returns the compact summary text.

    ``path`` is a file or a directory (relative paths resolve against
    ``workdir``). Directories are triaged over sorted evidence files
    (``EVIDENCE_EXTENSIONS``, capped at ``MAX_FILES``). The result is
    capped at ``max_output`` chars (line boundary; a truncation marker is
    appended).
    """
    p = Path(path)
    if not p.is_absolute():
        p = (workdir / p).resolve()
    if not p.exists():
        return f"log_triage: path not found: {path} (relative to {workdir})"

    targets: list[Path] = []
    skipped_note = ""
    if p.is_dir():
        files = [
            f for f in sorted(p.iterdir())
            if f.is_file() and f.suffix.lower() in EVIDENCE_EXTENSIONS and not f.name.startswith(".")
        ]
        if len(files) > MAX_FILES:
            skipped_note = f" ({MAX_FILES} of {len(files)} files shown)"
            files = files[:MAX_FILES]
        targets = files
        if not targets:
            return f"log_triage: no evidence files in {path} (extensions: {sorted(EVIDENCE_EXTENSIONS)})"
    else:
        targets = [p]

    results: list[str] = [f"log_triage: {len(targets)} file(s){skipped_note}, read-only"]
    total = 0
    for f in targets:
        st = _triage_file(f)
        if isinstance(st, str):
            results.append(st)
        else:
            total += st.n_lines
            results.extend(_fmt_file(st))
    out = "\n".join(results)
    if len(out) > max_output:
        out = out[:max_output].rsplit("\n", 1)[0] + f"\n…(truncated at {max_output} chars)"
    return out
