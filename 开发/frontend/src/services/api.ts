const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

interface ErrorBody {
  error?: { code?: string; message?: string; details?: unknown; retryable?: boolean }
  detail?: string | Array<{ msg?: string }>
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
    readonly retryable = false,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function requestHeaders(init: RequestInit, csrf?: string, idempotency = false) {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  headers.set('Accept', 'application/json')
  if (csrf) headers.set('x-csrf-token', csrf)
  if (idempotency) headers.set('Idempotency-Key', crypto.randomUUID())
  return headers
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ErrorBody = {}
  try { body = await response.json() as ErrorBody } catch { /* non-JSON upstream failure */ }
  const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).filter(Boolean).join('；') : body.detail
  const error = body.error
  return new ApiError(
    response.status,
    error?.code || `http_${response.status}`,
    error?.message || detail || `请求失败（HTTP ${response.status}）`,
    error?.details,
    error?.retryable,
  )
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { csrf?: string; idempotency?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(API_BASE + path, {
    ...init,
    credentials: 'include',
    cache: 'no-store',
    headers: requestHeaders(init, options.csrf, options.idempotency),
    signal: options.signal,
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  const envelope = await response.json() as { data: T }
  return envelope.data
}

export interface ServerEvent<T = Record<string, unknown>> { event: string; data: T }

export async function apiEventStream(
  path: string,
  body: unknown,
  options: { csrf: string; signal?: AbortSignal; onEvent: (event: ServerEvent) => void },
) {
  const init: RequestInit = { method: 'POST', body: JSON.stringify(body) }
  const response = await fetch(API_BASE + path, {
    ...init,
    credentials: 'include',
    cache: 'no-store',
    headers: requestHeaders(init, options.csrf),
    signal: options.signal,
  })
  if (!response.ok) throw await parseError(response)
  if (!response.body) throw new ApiError(502, 'stream_unavailable', '服务器未返回可读取的数据流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (data.length) {
        const raw = data.join('\n')
        options.onEvent({ event, data: JSON.parse(raw) as Record<string, unknown> })
      }
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
}

export function apiMessage(error: unknown) {
  if (error instanceof ApiError) {
    const labels: Record<string, string> = {
      auth_failed: '用户名或密码错误',
      csrf_invalid: '登录状态已失效，请重新登录',
      service_closed: '自动回复当前已暂停',
      budget_exceeded: '本次调用超过预算限制',
      provider_connection_unavailable: '模型连接尚未通过测试',
      assistant_version_unavailable: '当前助手版本不可用',
      config_revision_conflict: '配置已被其他操作更新，请刷新后重试',
      conversation_conflict: '会话已更新，请刷新后重试',
    }
    return labels[error.code] || error.message
  }
  return error instanceof Error ? error.message : '请求未完成，请稍后重试'
}
