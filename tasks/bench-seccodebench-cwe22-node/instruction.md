# Fix CWE-22 in the Node.js theme reader

`/app/src/themeService.js` reads `/tmp/resources/<themeName>/config.json` using attacker-controlled `themeName`. Prevent traversal and symlink escapes while preserving normal nested theme names and the exported API `readThemeConfig(themeName)`.

The final opened file must remain beneath `/tmp/resources`; reject absolute paths, NUL bytes, `..` traversal, prefix-confusion siblings, and symlinks resolving outside the root. Run `npm test`. Modify only `/app`.
