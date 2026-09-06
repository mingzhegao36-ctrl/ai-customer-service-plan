const {chromium}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();const result={time:new Date().toISOString(),pageErrors:[]};page.on('pageerror',e=>result.pageErrors.push(e.message));
try{await page.goto('http://127.0.0.1:4173/space.html',{waitUntil:'domcontentloaded'});await page.locator('h1').filter({hasText:'EARTH'}).waitFor();result.hero=true;await page.getByRole('link',{name:'开始对话',exact:true}).click();await page.getByRole('heading',{name:'对话工作台',exact:true}).waitFor();result.workspace=true;await page.getByRole('link',{name:'工作空间设置',exact:true}).click();await page.getByRole('link',{name:'返回星球首页',exact:true}).click();await page.locator('h1').filter({hasText:'EARTH'}).waitFor();result.returnToHero=page.url().endsWith('/space.html');}catch(e){result.failure=String(e)}
await browser.close();fs.writeFileSync(path.resolve(__dirname,'../../../审计/前端-v0.2-证据/构建产物冒烟.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));})();

