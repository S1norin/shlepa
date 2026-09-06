#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p=Path('/app/main.go')
s=p.read_text()
s=s.replace('"fmt"', '"fmt"\n\t"html"\n\t"strings"')
s=s.replace('\tif _, err := mail.ParseAddress(fromAddr);', '\tif strings.ContainsAny(fromAddr+toAddr+subject, "\\r\\n") { return "", fmt.Errorf("header injection") }\n\tif _, err := mail.ParseAddress(fromAddr);')
s=s.replace('fromAddr, toAddr, subject)', 'fromAddr, toAddr, html.EscapeString(subject))')
s=s.replace('userName, subject, feedbackContent)', 'html.EscapeString(userName), html.EscapeString(subject), html.EscapeString(feedbackContent))')
p.write_text(s)
PY
