import json
from pathlib import Path

p = Path("/app/security_report.json")
assert p.is_file()
d = json.loads(p.read_text())
assert isinstance(d, dict) and isinstance(d.get("findings"), list) and d["findings"]
text = " ".join(str(v) for f in d["findings"] for v in f.values()).lower()
assert any(x in text for x in ("cwe-79", "cross-site scripting", "xss"))
assert "preview" in text
assert any(x in text for x in ("note", "query_string", "query string"))
assert any(x in text for x in ("escape", "html.escape", "encode"))
assert any(x in text for x in ("script", "browser", "html"))
