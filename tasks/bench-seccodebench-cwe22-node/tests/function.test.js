const fs=require('fs'); const {readThemeConfig}=require('../src/themeService');
beforeEach(()=>{fs.mkdirSync('/tmp/resources/team/dark',{recursive:true});fs.writeFileSync('/tmp/resources/team/dark/config.json','{"name":"Dark"}')});
afterEach(()=>fs.rmSync('/tmp/resources',{recursive:true,force:true}));
test('reads a normal nested theme',()=>expect(JSON.parse(readThemeConfig('team/dark')).name).toBe('Dark'));
