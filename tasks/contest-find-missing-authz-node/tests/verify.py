import json
from pathlib import Path

p = Path("/app/security_report.json")
assert p.is_file()
d = json.loads(p.read_text())
fs = d.get("findings")
assert isinstance(fs, list) and fs
text = " ".join(str(v) for f in fs for v in f.values()).lower()
assert any(x in text for x in ("cwe-862", "missing authorization", "authorization"))
assert any(x in text for x in ("deleteinvoice", "delete invoice", "invoiceid"))
assert any(x in text for x in ("owner", "ownership", "cross-account", "another user"))
assert any(x in text for x in ("403", "role", "policy", "access control"))
