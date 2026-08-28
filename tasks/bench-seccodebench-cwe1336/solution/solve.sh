#!/usr/bin/env bash
# Reference solution for bench-seccodebench-cwe1336 (SSTI / Jinja2).
#
# The user input is no longer the template: render a FIXED template with
# the bio passed as data and HTML-escaped, so template syntax in user
# content is inert text.
set -euo pipefail

python3 - <<'PYEOF'
import pathlib

f = pathlib.Path("/app/profile_renderer/profile_renderer.py")
src = f.read_text()

import_line = "from jinja2 import Template\n"
fixed_import = "from jinja2 import Template\nfrom markupsafe import escape\n"

vulnerable = (
    "    template = Template(bio_content)\n"
    "    return template.render()"
)
fixed = (
    "    template = Template(\"<p>{{ bio }}</p>\")\n"
    "    return template.render(bio=escape(bio_content))"
)

if import_line not in src:
    raise SystemExit("ERROR: import line not found — source may have changed")
if vulnerable not in src:
    raise SystemExit("ERROR: vulnerable pattern not found — source may have changed")

src = src.replace(import_line, fixed_import)
src = src.replace(vulnerable, fixed)
f.write_text(src)
print("Patched /app/profile_renderer/profile_renderer.py")
PYEOF
