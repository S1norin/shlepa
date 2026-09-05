const fs = require('fs');
const path = require('path');
function readThemeConfig(themeName) {
  if (!themeName || typeof themeName !== 'string') throw new Error('Invalid theme name');
  return fs.readFileSync(path.join('/tmp/resources', themeName, 'config.json'), 'utf8');
}
module.exports = { readThemeConfig };
