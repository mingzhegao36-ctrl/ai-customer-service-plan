
const {chromium}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const output=path.resolve(__dirname,'../../../审计/前端-v0.2-证据');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1353,height:1163}});
 const result={browser:browser.version(),time:new Date().toISOString(),failures:[],errors:[]};
 page.on('requestfailed',r=>result.failures.push({url:r.url(),error:r.failure()?.errorText}));
 page.on('pageerror',e=>result.errors.push(e.message));
 try{
 await page.goto('http://127.0.0.1:5173/space.html',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>!document.documentElement.classList.contains('anim'));
 try{await page.waitForFunction(()=>Array.from(document.querySelectorAll('.planet img')).every(i=>i.complete&&i.naturalWidth>0)&&document.querySelector('video').currentTime>0,{},{timeout:30000})}catch{result.mediaWaitTimeout=true}
 result.media=await page.evaluate(()=>({videos:Array.from(document.querySelectorAll('video')).map(v=>({planet:v.dataset.planet,readyState:v.readyState,width:v.videoWidth,currentTime:v.currentTime,error:v.error?.code,paused:v.paused})),images:Array.from(document.querySelectorAll('.planet img')).map(i=>({planet:i.dataset.planet,width:i.naturalWidth,loaded:i.complete})),fonts:document.fonts.status,prata:document.fonts.check('16px Prata'),title:getComputedStyle(document.querySelector('h1')).fontFamily}));
 result.switchTiming=await page.evaluate(()=>{const original=Array.from(document.querySelectorAll('.planet img')).map(i=>i.src);const samples=[];for(let i=0;i<3;i++)for(const name of ['venus','mars','earth']){document.querySelector('[data-slot][data-planet="'+name+'"]').click();samples.push({planet:name,domSwitchMs:Number(document.documentElement.dataset.switchMs),shown:Array.from(document.querySelectorAll('.planet img.is-shown')).map(i=>i.dataset.planet)});}return {samples,unchangedSources:original.every((src,i)=>document.querySelectorAll('.planet img')[i].src===src),scope:'Synchronous DOM mutation duration; excludes download and browser paint'};});
 await page.waitForFunction(()=>document.querySelector('video[data-planet=earth]').readyState>=2&&!document.querySelector('video[data-planet=earth]').paused);
 await page.screenshot({path:path.join(output,'星球首页-1353.png')});
 await page.setViewportSize({width:390,height:844});
 await page.waitForFunction(()=>getComputedStyle(document.querySelector('.links')).opacity==='0');
 await page.screenshot({path:path.join(output,'星球首页-390.png')});
 await page.setViewportSize({width:1440,height:1000});
 await page.goto('http://127.0.0.1:5173/#/chat');
 await page.getByRole('heading',{name:'对话工作台',exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'工作台-1440.png'),fullPage:true});
 await page.goto('http://127.0.0.1:5173/#/assistant');
 await page.getByRole('heading',{name:'助手配置',exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'助手配置-1440.png'),fullPage:true});
 result.tabs=await page.locator('.section-tabs button').evaluateAll(nodes=>nodes.map(el=>({color:getComputedStyle(el).color,background:getComputedStyle(el).backgroundColor,height:el.getBoundingClientRect().height,pressed:el.getAttribute('aria-pressed')})));
 }catch(e){result.failure=String(e.stack)}
 await browser.close();fs.writeFileSync(path.join(output,'视觉复验.json'),JSON.stringify(result,null,2),'utf8');console.log(JSON.stringify(result,null,2));
})();
