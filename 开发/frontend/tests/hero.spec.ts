import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

test.beforeEach(async ({page}) => {
  // Asset-independent UI regressions. Live media is verified separately by capture-preview.cjs.
  await page.route('https://d8j0ntlcm91z4.cloudfront.net/**', route => {
    if(route.request().url().endsWith('.png')) return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><circle cx="4" cy="4" r="4" fill="#345"/></svg>'})
    return route.abort()
  })
  await page.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:''}))
})
test('FE-A01：HTML 文件可独立打开，无外部脚本、无框架入口', async ({page}) => {
  const file=resolve('public/space.html'),html=readFileSync(file,'utf8')
  expect(html).not.toMatch(/__\w+__/)
  expect((html.match(/<style>/g)||[])).toHaveLength(1)
  expect(html).not.toMatch(/<script[^>]+src=/)
  expect(html).not.toContain('/src/main.ts')
  await page.goto(pathToFileURL(file).href)
  await expect(page.locator('h1')).toHaveText('EARTH')
  await expect(page.locator('video')).toHaveCount(3)
  await expect(page.locator('.planet img')).toHaveCount(6)
  await expect(page.locator('#primary-cta')).toHaveAttribute('href','http://127.0.0.1:5173/#/chat')
})
test('初始只设置 Earth 视频 src，意图预热后可逆切换且不改图片 src', async ({page}) => {
  await page.addInitScript(()=>{window.requestIdleCallback=()=>0})
  await page.goto('/space.html')
  await expect(page.locator('video[src]')).toHaveCount(1)
  await expect(page.locator('[data-slot=l]')).toHaveAttribute('data-planet','venus')
  await expect(page.locator('[data-slot=r]')).toHaveAttribute('data-planet','mars')
  const srcs=await page.locator('.planet img').evaluateAll(imgs=>imgs.map(i=>i.getAttribute('src')))
  await page.getByRole('button',{name:'显示 VENUS',exact:true}).focus()
  await expect(page.locator('video[data-planet=venus]')).toHaveAttribute('src',/\.mp4$/)
  for(const name of ['VENUS','MARS','EARTH']) {
    await page.getByRole('button',{name:'显示 '+name,exact:true}).click()
    await expect(page.locator('h1')).toHaveText(name)
    await expect(page.locator('video.is-active')).toHaveAttribute('data-planet',name.toLowerCase())
    await expect(page.locator('.planet img.is-shown')).toHaveCount(2)
  }
  expect(await page.locator('.planet img').evaluateAll(imgs=>imgs.map(i=>i.getAttribute('src')))).toEqual(srcs)
  await expect(page.locator('[data-slot=l]')).toHaveAttribute('data-planet','venus')
  await expect(page.locator('[data-slot=r]')).toHaveAttribute('data-planet','mars')
})
test('入口打开相应模块、蓝图弹窗及聊天工作台', async ({page}) => {
  await page.goto('/space.html')
  await page.getByRole('link',{name:'功能模块',exact:true}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('.module-list li')).toHaveCount(7)
  await page.getByRole('button',{name:'关闭功能模块'}).click()
  await page.getByRole('button',{name:'显示 MARS',exact:true}).click()
  await page.getByRole('link',{name:'查看演进蓝图',exact:true}).click()
  await expect(page.getByRole('dialog')).toContainText('V4')
  await page.keyboard.press('Escape')
  await page.getByRole('button',{name:'显示 EARTH',exact:true}).click()
  await page.getByRole('link',{name:'开始对话',exact:true}).click()
  await expect(page.getByRole('heading',{name:'对话工作台',exact:true})).toBeVisible()
})
test('手机导航打开、Escape 返回焦点、链接点击关闭、点外部关闭', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await page.goto('/space.html')
  const burger=page.getByRole('button',{name:'打开导航',exact:true})
  await expect(page.locator('.links')).toBeHidden()
  await burger.click()
  await expect(page.locator('.links')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(burger).toBeFocused()
  await expect(burger).toHaveAttribute('aria-expanded','false')
  await burger.click()
  await page.getByRole('link',{name:'使用说明',exact:true}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(burger).toHaveAttribute('aria-expanded','false')
  await page.keyboard.press('Escape')
  await burger.click()
  const outside = await page.locator('.preview-note').boundingBox()
  await page.mouse.click(outside!.x + outside!.width / 2, outside!.y + outside!.height / 2)
  await expect(burger).toHaveAttribute('aria-expanded','false')
})
test('入场动画完成后清理样式，暂停控件可切换', async ({page}) => {
  await page.goto('/space.html')
  await expect(page.locator('html')).not.toHaveClass(/anim|play/,{timeout:5000})
  await expect(page.locator('h1 .ent-line')).toHaveCSS('transform','none')
  await page.getByRole('button',{name:'暂停背景',exact:true}).click()
  await expect(page.getByRole('button',{name:'播放背景',exact:true})).toHaveAttribute('aria-pressed','true')
})
test('减少动画模式不启动入场；切换仍更新静帧', async ({page}) => {
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.goto('/space.html')
  await expect(page.locator('html')).not.toHaveClass(/anim|play/)
  await expect(page.locator('video.is-active')).toBeHidden()
  await page.getByRole('button',{name:'显示 VENUS',exact:true}).click()
  await expect(page.locator('h1')).toHaveText('VENUS')
  await expect(page.locator('.sky')).toHaveCSS('background-image',/cf55d1d8/)
  await expect(page.locator('video[data-planet=venus]')).not.toHaveAttribute('src')
})
test('全部图片和字体不可用时，导航与核心文案仍可使用', async ({page}) => {
  await page.route('https://d8j0ntlcm91z4.cloudfront.net/**',route=>route.abort())
  await page.route('https://fonts.googleapis.com/**',route=>route.abort())
  await page.goto('/space.html')
  await expect(page.locator('html')).not.toHaveClass(/anim|play/,{timeout:5000})
  await expect(page.locator('h1')).toHaveText('EARTH')
  await page.getByRole('link',{name:'功能模块',exact:true}).click()
  await expect(page.getByRole('dialog')).toContainText('对话工作台')
})
test('320–2560 像素宽度下三颗星球、短屏和工作台页面不横向溢出', async ({page}) => {
  test.setTimeout(60000)
  const widths=[[320,720],[390,844],[500,700],[579,800],[580,900],[768,1024],[1030,900],[1031,900],[1353,1163],[1440,900],[2560,1440],[844,390],[640,480]]
  const samples=[]
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.goto('/space.html')
  for(const [width,height] of widths) {
    await page.setViewportSize({width,height})
    for(const name of ['EARTH','VENUS','MARS']){
      if((await page.locator('h1').innerText())!==name)await page.getByRole('button',{name:'显示 '+name,exact:true}).click()
      const bounds=await page.evaluate(()=>{
        const cta=document.getElementById('primary-cta')!.getBoundingClientRect()
        return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,ctaBottom:cta.bottom,height:innerHeight}
      })
      expect(bounds.scrollWidth).toBeLessThanOrEqual(width)
      expect(bounds.ctaBottom).toBeLessThan(height)
      samples.push({page:'hero',planet:name,...bounds})
    }
  }
  const routes={chat:'对话工作台',history:'会话记录',assistant:'助手配置',connections:'模型连接',usage:'用量与预算',tasks:'任务中心',settings:'工作空间设置',modules:'功能模块与演进',login:'进入你的'}
  for(const [width,height] of [[320,720],[390,844],[768,1024],[1024,768],[1440,900],[2560,1440]]) {
    await page.setViewportSize({width,height})
    for(const [route,heading] of Object.entries(routes)){
      await page.goto('/#/'+route)
      await expect(page.locator('h1')).toContainText(heading)
      const sw=await page.evaluate(()=>document.documentElement.scrollWidth)
      expect(sw).toBeLessThanOrEqual(width)
      samples.push({page:route,width,height,scrollWidth:sw})
    }
  }
  await test.info().attach('layout-samples.json',{body:JSON.stringify(samples,null,2),contentType:'application/json'})
})
