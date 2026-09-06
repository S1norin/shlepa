#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p=Path('/app/src/themeService.js')
p.write_text("""const fs=require('fs'); const path=require('path');
function readThemeConfig(themeName){
 if(typeof themeName!=='string'||!themeName||themeName.includes('\\0')||path.isAbsolute(themeName)) throw new Error('Invalid theme name');
 const parts=themeName.split(/[\\\\/]+/); if(parts.includes('..')) throw new Error('Path traversal');
 const ROOT=fs.realpathSync('/tmp/resources');
 const actual=fs.realpathSync(path.join(ROOT,...parts,'config.json'));
 if(actual!==ROOT&&!actual.startsWith(ROOT+path.sep)) throw new Error('Path escape');
 return fs.readFileSync(actual,'utf8');
}
module.exports={readThemeConfig};
""")
PY
