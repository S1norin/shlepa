const fs=require('fs'); const {readThemeConfig}=require('../src/themeService');
beforeEach(()=>{fs.mkdirSync('/tmp/resources/ok',{recursive:true});fs.writeFileSync('/tmp/resources/ok/config.json','ok');fs.mkdirSync('/tmp/outside',{recursive:true});fs.writeFileSync('/tmp/outside/config.json','SECRET');try{fs.symlinkSync('/tmp/outside','/tmp/resources/link','dir')}catch(e){}});
afterEach(()=>{fs.rmSync('/tmp/resources',{recursive:true,force:true});fs.rmSync('/tmp/outside',{recursive:true,force:true})});
for (const value of ['../outside','/tmp/outside','..\\outside','\0../outside']) test(`blocks ${JSON.stringify(value)}`,()=>{let r;try{r=readThemeConfig(value)}catch(e){}expect(r).not.toBe('SECRET')});
test('blocks symlink escape',()=>{let r;try{r=readThemeConfig('link')}catch(e){}expect(r).not.toBe('SECRET')});
