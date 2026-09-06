import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import { liveBackendEnv } from './live-test-env'

const providerSecret = 'frontend-live-provider-secret'

function startProvider() {
  const server = createServer((request, response) => {
    if (request.headers.authorization !== `Bearer ${providerSecret}`) {
      response.writeHead(401, { 'content-type': 'application/json' }).end('{"error":"invalid key"}')
      return
    }
    if (request.method === 'GET' && request.url === '/v1/models') {
      response.writeHead(200, { 'content-type': 'application/json' }).end('{"data":[{"id":"frontend-live-model"}]}')
      return
    }
    if (request.method !== 'POST' || request.url !== '/v1/chat/completions') {
      response.writeHead(404, { 'content-type': 'application/json' }).end('{"error":"not found"}')
      return
    }
    let raw = ''
    request.on('data', chunk => { raw += chunk })
    request.on('end', () => {
      const body = JSON.parse(raw) as { stream?: boolean }
      if (body.stream) {
        const chunks = [
          { choices: [{ delta: { content: '前后端联调' } }] },
          { choices: [{ delta: { content: '成功' } }], usage: { prompt_tokens: 12, completion_tokens: 4 } },
        ]
        response.writeHead(200, { 'content-type': 'text/event-stream', 'x-request-id': 'frontend-live-stream' })
        chunks.forEach(chunk => response.write(`data: ${JSON.stringify(chunk)}\n\n`))
        response.end('data: [DONE]\n\n')
      } else {
        response.writeHead(200, { 'content-type': 'application/json', 'x-request-id': 'frontend-live-complete' })
        response.end(JSON.stringify({ choices: [{ message: { content: 'connection ok' } }], usage: { prompt_tokens: 6, completion_tokens: 2 } }))
      }
    })
  })
  return new Promise<typeof server>((resolve, reject) => {
    server.once('error', reject)
    server.listen(9198, '127.0.0.1', () => resolve(server))
  })
}

function processJobs() {
  const python = process.platform === 'win32' ? path.resolve('../backend/.venv/Scripts/python.exe') : path.resolve('../backend/.venv/bin/python')
  const code = 'import asyncio\nfrom app.worker import process_one_job\nasync def main():\n    for _ in range(10):\n        if not await process_one_job(): break\nasyncio.run(main())'
  return new Promise<void>((resolve, reject) => {
    const child = spawn(python, ['-c', code], { cwd: path.resolve('../backend'), env: { ...process.env, ...liveBackendEnv }, stdio: 'pipe' })
    let error = ''
    child.stderr.on('data', chunk => { error += chunk })
    child.on('error', reject)
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(error || `worker exited ${code}`)))
  })
}

test('真实后端：登录、预算、连接、助手版本与流式对话', async ({ page }) => {
  const provider = await startProvider()
  try {
    await page.goto('/#/login')
    await page.getByLabel('用户名').fill('admin')
    await page.getByLabel('密码').fill('frontend-live-password')
    await page.getByRole('button', { name: '登录工作空间' }).click()
    await expect(page.getByText('后端已连接')).toBeVisible()

    await page.goto('/#/usage')
    await page.getByLabel('每日上限（元）').fill('20')
    await page.getByLabel('每月上限（元）').fill('200')
    await page.getByRole('button', { name: '保存预算策略' }).click()
    await expect(page.getByRole('status')).toContainText('预算策略已更新')

    await page.goto('/#/connections')
    await page.getByLabel('连接名称').fill('frontend-live-provider')
    await page.getByLabel('API 地址').fill('http://127.0.0.1:9198/v1')
    await page.getByLabel('模型标识').fill('frontend-live-model')
    const secret = page.getByLabel(/API Key/)
    if (await secret.isEditable()) await secret.fill(providerSecret)
    await page.getByLabel('输入价／百万 Token').fill('1')
    await page.getByLabel('输出价／百万 Token').fill('2')
    await page.getByRole('button', { name: '保存并真实测试' }).click()
    await processJobs()
    await expect(page.locator('.card-header .badge')).toContainText('连接可用')

    await page.goto('/#/assistant')
    await page.getByLabel('助手名称').fill('前后端联调助手')
    await page.getByLabel('一句话介绍').fill('验证真实 API 和流式响应')
    await page.getByLabel('系统提示词').fill('请简洁回答，并只返回已确认的信息。')
    await page.getByRole('button', { name: '保存为草稿版本' }).click()
    await page.getByRole('button', { name: '启用并设为默认' }).first().click()
    await expect(page.getByRole('status')).toContainText('已启用并设为默认版本')

    await page.goto('/#/chat')
    await expect(page.getByText('服务可用 · 后端已连接')).toBeVisible()
    await page.getByRole('button', { name: '新建对话' }).click()
    await page.getByRole('textbox', { name: '输入消息' }).fill('请验证前后端连接')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect(page.locator('.message-text').last()).toContainText('前后端联调成功')

    await page.reload()
    await expect(page.locator('.message-text').last()).toContainText('前后端联调成功')
  } finally {
    await new Promise<void>(resolve => provider.close(() => resolve()))
  }
})
