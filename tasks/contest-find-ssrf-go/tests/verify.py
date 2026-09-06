import json
from pathlib import Path

p = Path("/app/security_report.json")
assert p.is_file()
d = json.loads(p.read_text())
fs = d.get("findings")
assert isinstance(fs, list) and fs
text = " ".join(str(v) for f in fs for v in f.values()).lower()
assert any(x in text for x in ("cwe-918", "server-side request forgery", "ssrf"))
assert any(x in text for x in ("fetchcard", "http.get", "rawurl"))
assert any(x in text for x in ("localhost", "127.0.0.1", "private", "link-local", "metadata"))
assert "redirect" in text
assert any(x in text for x in ("resolve", "resolved", "dns", "ip address"))
