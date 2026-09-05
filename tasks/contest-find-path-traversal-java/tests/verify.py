import json
from pathlib import Path

p = Path("/app/security_report.json")
assert p.is_file()
d = json.loads(p.read_text())
fs = d.get("findings")
assert isinstance(fs, list) and fs
text = " ".join(str(v) for f in fs for v in f.values()).lower()
assert any(x in text for x in ("cwe-22", "path traversal", "directory traversal"))
assert any(x in text for x in ("saveexport", "files.write", "resolve"))
assert ".." in text
assert any(x in text for x in ("normalize", "canonical", "realpath", "real path"))
assert any(x in text for x in ("symlink", "symbolic link"))
