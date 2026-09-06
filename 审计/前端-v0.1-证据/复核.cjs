
const { chromium } = require('E:/ai-customer-service-plan/开发/frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const output = __dirname;
const result = { checkedAt: new Date().toISOString(), consoleErrors: [], routes: [], layouts: [], cases: [] };
const headings = {chat:'对话工作台',history:'会话记录',assistant:'助手配置',connections:'模型连接',usage:'用量与预算',tasks:'任务中心',settings:'工作空间设置',modules:'功能模块与演进',login:'进入你的'};
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  result.browserVersion = browser.version();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', e => result.consoleErrors.push(String(e)));
  page.on('console', m => { if(m.type() === 'error') result.consoleErrors.push(m.text()); });
  async function ready(route) { await page.waitForFunction(text => document.querySelector('h1')?.textContent?.includes(text), headings[route], {timeout:15000}); }
  try {
    for(const route of ['chat','history','assistant','connections','usage','tasks','settings','modules','login']) {
      await page.goto('http://127.0.0.1:5173/#/' + route);
      await ready(route);
      result.routes.push({ route, title: await page.locator('h1').innerText(), horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth) });
      if(['chat','assistant','history','login'].includes(route)) await page.screenshot({ path: path.join(output, route + '-1440.png'), fullPage: true });
    }
    await page.goto('http://127.0.0.1:5173/#/chat');
    await page.getByLabel('输入消息', {exact:true}).fill('如何控制 Token 成本？');
    await page.getByRole('button', {name:'发送消息',exact:true}).click();
    await page.locator('.message-actions').waitFor();
    result.cases.push({ name: '聊天生成', pass: (await page.locator('.message-text').innerText()).includes('预设') });
    await page.selectOption('#scenario','disconnect');
    await page.getByRole('button', {name:/重新生成/}).click();
    await page.locator('.message-notice').waitFor();
    result.cases.push({ name:'重试中断保留旧答案', pass:(await page.locator('.message-notice').innerText()).includes('上一版有效答案') });
    await page.screenshot({ path:path.join(output,'chat-interrupted-1440.png'),fullPage:true });
    for(const [width,height] of [[320,720],[390,844],[768,1024],[1024,768],[1440,900],[2560,1440]]) {
      await page.setViewportSize({width,height});
      for(const route of ['chat','history','assistant','connections','usage','tasks','settings','modules','login']) {
        await page.goto('http://127.0.0.1:5173/#/'+route);
        await ready(route);
        result.layouts.push(await page.evaluate(({route,width,height}) => ({
          route,width,height,scrollWidth:document.documentElement.scrollWidth,
          overflow: document.documentElement.scrollWidth > innerWidth,
          bodyHeight:document.documentElement.scrollHeight,
        }),{route,width,height}));
      }
      if(width===390) {
        await page.goto('http://127.0.0.1:5173/#/chat');
        await ready('chat');
        await page.screenshot({path:path.join(output,'chat-390.png'),fullPage:true});
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.goto('http://127.0.0.1:5173/#/chat');
    result.domain = await page.evaluate(async () => {
      const { createDemoWorkspace } = await import('/src/stores/workspace.ts');
      const wait = ms => new Promise(resolve=>setTimeout(resolve,ms));
      const checks = [];
      const ws = createDemoWorkspace();
      const initialHeld=ws.usageTotals.value.held;
      ws.send('测试停止');
      ws.stop();
      await wait(500);
      checks.push({name:'停止后迟到回调不续写，预留保留',pass:ws.state.usage[0].status==='unknown'&&ws.usageTotals.value.held===initialHeld+20&&ws.currentConversation.value.turns[0].answers[0].text==='' });
      ws.selectConversation('sample-guide');
      ws.exportConversations(['sample-guide']);
      const id=ws.state.jobs[0].id;
      await wait(800);
      checks.push({name:'来源有效时可下载',pass:!!ws.downloadPayload(id)});
      ws.removeConversation('sample-guide');
      checks.push({name:'删除后下载立即失效',pass:!ws.downloadPayload(id)&&!ws.state.jobs.find(j=>j.id===id).payload});
      ws.exportConversations(['sample-policy']);
      const pending=ws.state.jobs[0].id;
      ws.removeConversation('sample-policy');
      await wait(800);
      checks.push({name:'准备中删除阻断导出',pass:ws.state.jobs.find(j=>j.id===pending).status==='blocked'&&!ws.downloadPayload(pending)});
      ws.setRole('member');
      checks.push({name:'普通身份拒绝管理员动作',pass:ws.saveBudget(10,20)===false&&ws.setService(false)===false&&ws.exportConversations(['member-welcome'])===false&&ws.visibleConversations.value.every(c=>c.owner==='member')});
      ws.dispose();
      // Reproduce revalidation race: test A pending, then save B before A finishes.
      const live = (await import('/src/stores/workspace.ts')).workspace;
      return {checks, currentConnection:live.state.connection};
    });
    await page.goto('http://127.0.0.1:5173/#/connections');
    await page.getByRole('button',{name:'模拟连接测试',exact:true}).click();
    await page.locator('input[type="url"]').fill('https://changed.example.com/v1');
    await page.getByRole('button',{name:'保存示例配置',exact:true}).click();
    await page.waitForTimeout(700);
    result.connectionRace=await page.evaluate(async()=>{
      const {workspace}=await import('/src/stores/workspace.ts');
      return { savedBaseUrl:workspace.state.connection.baseUrl,tested:workspace.state.connection.tested };
    });
    await page.goto('http://127.0.0.1:5173/#/assistant'); await ready('assistant');
    result.tabs = await page.locator('.section-tabs button').evaluateAll(nodes => nodes.map(el => { const s=getComputedStyle(el); return {text:el.textContent,background:s.backgroundColor,color:s.color,width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,fontSize:s.fontSize}; }));
    await page.screenshot({path:path.join(output,'assistant-1440.png'),fullPage:true});
    await page.goto('http://127.0.0.1:5173/#/login');
    await page.getByRole('button',{name:/内部使用者/}).click();
    await page.waitForURL('**/#/chat');
    await page.evaluate(()=> {location.hash='/usage'});
    await page.waitForTimeout(300);
    result.cases.push({name:'普通身份直接访问管理路由被重定向',pass:page.url().endsWith('/#/chat')});
    await page.goto('http://127.0.0.1:5173/space.html');
    await ready('chat');
    result.home={url:page.url(),title:await page.title(),videoCount:await page.locator('video').count(),planetSlots:await page.locator('[data-slot]').count()};
  } catch(e) { result.failure=String(e.stack || e); }
  await browser.close();
  fs.writeFileSync(path.join(output,'结果.json'),JSON.stringify(result,null,2),'utf8');
  console.log(JSON.stringify(result,null,2));
})();
