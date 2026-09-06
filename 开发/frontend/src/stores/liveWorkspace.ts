import { computed, reactive } from 'vue'
import { totals } from '../domain/rules'
import { ApiError, apiEventStream, apiMessage, apiRequest } from '../services/api'
import type { Answer, AssistantVersion, Connection, Conversation, DemoJob, Role, Scenario, Turn, UsageEntry } from '../types'

type Json = Record<string, unknown>
type ConversationDto = {
  id: string; assistant_id: string | null; current_assistant_version_id: string | null
  subject: string; status: string; revision: number; turn_count: number
  last_activity_at: string | null; created_at: string
}
type MessageDto = { id: string; turn_id: string; role: string; content: string; created_at: string }
type AssistantDto = { id: string; name: string; description: string | null; revision: number; default_version_id: string | null }
type VersionDto = { id: string; assistant_id: string; deployment_id: string; policy_version: number; revision: number; status: 'active' | 'draft' | 'revoked'; created_at: string; prompt?: string }
type DeploymentDto = { id: string; model_id: string; currency: string; input_price_per_million: string; output_price_per_million: string; max_input_tokens: number; max_output_tokens: number }
type ConnectionDto = { id: string; name: string; base_url: string; secret_configured: boolean; secret_hint: string | null; revision: number; status: string; deployments: DeploymentDto[] }
type BudgetDto = {
  version: number; currency: string; workspace_daily_limit: string; workspace_monthly_limit: string
  conversation_limit: string; turn_limit: string; max_attempts_per_turn: number
  max_input_tokens: number; max_output_tokens: number
  accounts?: Array<{ scope: string; spent: string; held: string }>
}

const uid = (prefix: string) => `${prefix}-${crypto.randomUUID()}`
const formatTime = (value?: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
  : '刚刚'
const cents = (value: string | number | undefined) => Math.round(Number(value || 0) * 100)

export function createLiveWorkspace() {
  const state = reactive({
    mode: 'live' as 'demo' | 'live',
    apiStatus: 'connecting' as 'connecting' | 'ready' | 'offline',
    loading: false,
    authError: '',
    userName: '',
    role: null as Role | null,
    workspaceName: '知应客服工作空间',
    conversations: [] as Conversation[],
    selectedId: '',
    usage: [] as UsageEntry[],
    jobs: [] as DemoJob[],
    serviceEnabled: false,
    assistantName: '尚未配置助手',
    assistantDescription: '管理员完成模型连接、预算和助手版本配置后即可开始对话。',
    versions: [] as AssistantVersion[],
    connection: {
      name: '', baseUrl: '', model: '', tested: false, status: 'unconfigured',
      currency: 'CNY', inputPrice: 0, outputPrice: 0, maxInputTokens: 4000, maxOutputTokens: 1200,
    } as Connection,
    dailyLimitCents: 0,
    monthlyLimitCents: 0,
    scenario: 'normal' as Scenario,
    toast: '',
  })

  let csrf = ''
  let workspaceRevision = 1
  let serviceEpoch = 1
  let assistant: AssistantDto | undefined
  let connectionDto: ConnectionDto | undefined
  let budget: BudgetDto | undefined
  const conversationDtos = new Map<string, ConversationDto>()
  let streamController: AbortController | undefined
  let toastTimer: ReturnType<typeof setTimeout> | undefined

  const runningId = computed(() => state.conversations.flatMap(item => item.turns).flatMap(turn => turn.answers).find(answer => answer.status === 'running')?.id)
  const visibleConversations = computed(() => state.conversations)
  const currentConversation = computed(() => state.conversations.find(item => item.id === state.selectedId))
  const usageTotals = computed(() => totals(state.usage))
  const availableCents = computed(() => Math.max(0, Math.min(state.dailyLimitCents, state.monthlyLimitCents) - usageTotals.value.spent - usageTotals.value.held))
  const activeVersion = computed(() => state.mode === 'live'
    ? state.versions.find(item => item.id === assistant?.default_version_id && item.state === 'active')
    : state.versions.find(item => item.state === 'active'))

  function notify(message: string) {
    state.toast = message
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { state.toast = '' }, 4200)
  }

  function resetSession() {
    csrf = ''
    state.role = null
    state.userName = ''
    state.conversations = []
    state.selectedId = ''
    state.usage = []
    state.jobs = []
  }

  function assignUser(payload: { user: { username: string; role: Role; workspace?: { name: string } | null } }) {
    state.role = payload.user.role
    state.userName = payload.user.username
    if (payload.user.workspace?.name) state.workspaceName = payload.user.workspace.name
  }

  async function initialize() {
    state.loading = true
    state.apiStatus = 'connecting'
    try {
      const me = await apiRequest<{ user: { username: string; role: Role; workspace?: { name: string } | null } }>('/auth/me')
      assignUser(me)
      csrf = (await apiRequest<{ csrf_token: string }>('/auth/csrf')).csrf_token
      await refreshAll()
      state.apiStatus = 'ready'
      return true
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) state.apiStatus = 'offline'
      else state.apiStatus = 'ready'
      resetSession()
      return false
    } finally { state.loading = false }
  }

  async function login(username: string, password: string, remember = false) {
    state.loading = true
    state.authError = ''
    try {
      const preauth = await apiRequest<{ csrf_token: string }>('/auth/csrf')
      const result = await apiRequest<{
        user: { username: string; role: Role; workspace?: { name: string } | null }
        session: { csrf_token: string }
      }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password, remember_me: remember }),
      }, { csrf: preauth.csrf_token })
      csrf = result.session.csrf_token
      assignUser(result)
      await refreshAll()
      state.apiStatus = 'ready'
      return true
    } catch (error) {
      state.authError = apiMessage(error)
      state.apiStatus = error instanceof ApiError ? 'ready' : 'offline'
      return false
    } finally { state.loading = false }
  }

  async function logout() {
    try { if (csrf) await apiRequest<void>('/auth/logout', { method: 'POST' }, { csrf }) } catch { /* clear local session even when the API is unavailable */ }
    streamController?.abort()
    resetSession()
  }

  async function refreshAll() {
    await Promise.all([loadWorkspace(), loadService(), loadAssistants(), loadConversations(), loadJobs()])
    if (state.role === 'admin') {
      await Promise.all([loadConnection(), loadBudget()])
      await loadUsage()
    }
  }

  async function loadWorkspace() {
    const data = await apiRequest<{ name: string; revision: number }>('/workspace')
    state.workspaceName = data.name
    workspaceRevision = data.revision
  }

  async function loadService() {
    const data = await apiRequest<{ mode: string; authorization_epoch: number }>('/service-mode')
    state.serviceEnabled = data.mode === 'open'
    serviceEpoch = data.authorization_epoch
  }

  async function loadConversations() {
    const data = await apiRequest<{ items: ConversationDto[] }>('/conversations?limit=100')
    const localEmpty = state.conversations.filter(item => !data.items.some(dto => dto.id === item.id) && !item.turns.length)
    conversationDtos.clear()
    data.items.forEach(item => conversationDtos.set(item.id, item))
    const mapped = data.items.map(mapConversation)
    state.conversations = [...localEmpty, ...mapped]
    if (!state.selectedId || !state.conversations.some(item => item.id === state.selectedId)) state.selectedId = state.conversations[0]?.id || ''
    if (state.selectedId && conversationDtos.has(state.selectedId)) await loadConversation(state.selectedId)
  }

  function mapConversation(dto: ConversationDto): Conversation {
    const previous = state.conversations.find(item => item.id === dto.id)
    return {
      id: dto.id,
      title: dto.subject,
      owner: state.role || 'member',
      updatedAt: formatTime(dto.last_activity_at || dto.created_at),
      turns: previous?.turns || [],
    }
  }

  async function loadConversation(id: string) {
    const [details, messages] = await Promise.all([
      apiRequest<ConversationDto>(`/conversations/${id}`),
      apiRequest<{ items: MessageDto[] }>(`/conversations/${id}/messages?limit=100`),
    ])
    conversationDtos.set(id, details)
    const item = state.conversations.find(value => value.id === id)
    if (!item) return
    item.title = details.subject
    item.updatedAt = formatTime(details.last_activity_at || details.created_at)
    const turns = new Map<string, Turn>()
    for (const message of messages.items) {
      const turn = turns.get(message.turn_id) || { id: message.turn_id, question: '', answers: [] }
      if (message.role === 'user') turn.question = message.content
      if (message.role === 'assistant') {
        turn.answers.push({ id: message.id, text: message.content, status: 'completed', inputTokens: 0, outputTokens: 0 })
        turn.activeAnswerId = message.id
      }
      turns.set(message.turn_id, turn)
    }
    item.turns = [...turns.values()]
  }

  async function loadAssistants() {
    const data = await apiRequest<{ items: AssistantDto[] }>('/assistants')
    assistant = data.items[0]
    if (!assistant) {
      state.assistantName = '尚未配置助手'
      state.assistantDescription = '请由管理员完成助手配置。'
      state.versions = []
      return
    }
    state.assistantName = assistant.name
    state.assistantDescription = assistant.description || ''
    if (state.role === 'admin') {
      const versions = await apiRequest<{ items: VersionDto[] }>(`/assistants/${assistant.id}/versions`)
      state.versions = versions.items.map(item => ({
        id: item.id,
        prompt: item.prompt || '',
        state: item.status,
        date: formatTime(item.created_at),
        revision: item.revision,
        deploymentId: item.deployment_id,
      }))
    } else {
      state.versions = assistant.default_version_id
        ? [{ id: assistant.default_version_id, prompt: '', state: 'active', date: '' }]
        : []
    }
  }

  async function loadConnection() {
    const data = await apiRequest<{ items: ConnectionDto[] }>('/provider-connections')
    connectionDto = data.items[0]
    if (!connectionDto) return
    const deployment = connectionDto.deployments[0]
    state.connection = {
      id: connectionDto.id,
      name: connectionDto.name,
      baseUrl: connectionDto.base_url,
      model: deployment?.model_id || '',
      tested: connectionDto.status === 'ready',
      status: connectionDto.status,
      revision: connectionDto.revision,
      secretConfigured: connectionDto.secret_configured,
      secretHint: connectionDto.secret_hint || undefined,
      deploymentId: deployment?.id,
      currency: deployment?.currency || 'CNY',
      inputPrice: Number(deployment?.input_price_per_million || 0),
      outputPrice: Number(deployment?.output_price_per_million || 0),
      maxInputTokens: deployment?.max_input_tokens || 4000,
      maxOutputTokens: deployment?.max_output_tokens || 1200,
    }
  }

  async function loadBudget() {
    try {
      budget = await apiRequest<BudgetDto>('/budget-policies/current')
      state.dailyLimitCents = cents(budget.workspace_daily_limit)
      state.monthlyLimitCents = cents(budget.workspace_monthly_limit)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) throw error
      budget = undefined
      state.dailyLimitCents = 0
      state.monthlyLimitCents = 0
    }
  }

  async function loadUsage() {
    const data = await apiRequest<{ items: Array<{ attempt_id: string; model_id: string; status: string; usage: { input_tokens?: number; output_tokens?: number } | null; created_at: string }> }>('/usage?limit=100')
    const entries: UsageEntry[] = data.items.map(item => ({
      id: item.attempt_id,
      label: item.model_id,
      status: item.status === 'completed' ? 'actual' : item.status === 'unknown' ? 'unknown' : 'running',
      tokens: Number(item.usage?.input_tokens || 0) + Number(item.usage?.output_tokens || 0),
      costCents: 0,
      heldCents: 0,
      time: formatTime(item.created_at),
    }))
    const account = budget?.accounts?.find(item => item.scope === 'workspace_daily')
    if (account && (Number(account.spent) || Number(account.held))) entries.unshift({
      id: 'workspace-daily-account', label: '工作空间日账本汇总', status: Number(account.held) ? 'unknown' : 'actual',
      tokens: 0, costCents: cents(account.spent), heldCents: cents(account.held), time: '当前周期',
    })
    state.usage = entries
  }

  async function loadJobs() {
    const data = await apiRequest<{ items: Array<{ id: string; type: string; status: string; stage: string; created_at: string; updated_at: string; error_code: string | null; retryable: boolean }> }>('/jobs?limit=100')
    state.jobs = data.items.map(item => ({
      id: item.id,
      title: item.type === 'provider_connection_test' ? '模型连接测试' : item.type === 'conversation_deletion' ? '会话删除' : item.type,
      type: item.type === 'provider_connection_test' ? 'provider_test' : item.type === 'conversation_deletion' ? 'delete' : 'reconcile',
      status: (['queued', 'running', 'completed', 'failed', 'blocked'].includes(item.status) ? item.status : 'blocked') as DemoJob['status'],
      createdAt: formatTime(item.created_at),
      detail: `${item.stage}${item.error_code ? ` · ${item.error_code}` : ''}${item.retryable ? ' · 可重试' : ''}`,
    }))
  }

  async function newConversation() {
    if (!state.role) return false
    if (!assistant?.default_version_id) { notify('请先配置并启用助手版本'); return false }
    try {
      const dto = await apiRequest<ConversationDto>('/conversations', {
        method: 'POST', body: JSON.stringify({ subject: '新的对话', assistant_id: assistant.id }),
      }, { csrf, idempotency: true })
      conversationDtos.set(dto.id, dto)
      state.conversations.unshift(mapConversation(dto))
      state.selectedId = dto.id
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  function selectConversation(id: string) {
    if (!state.conversations.some(item => item.id === id)) return false
    state.selectedId = id
    if (conversationDtos.has(id)) void loadConversation(id).catch(error => notify(apiMessage(error)))
    return true
  }

  function startReason() {
    if (!state.role) return '请先登录'
    if (!currentConversation.value) return '请新建一个会话'
    if (runningId.value) return '请等待当前回复结束'
    if (!state.serviceEnabled) return '自动回复已暂停，请联系管理员'
    if (!activeVersion.value) return '当前没有已启用的助手版本'
    return ''
  }

  async function send(question: string) {
    const reason = startReason()
    if (reason) { notify(reason); return false }
    const content = question.trim()
    if (!content) return false
    if (content.length > 8192) { notify('单条消息最多 8,192 个字符'); return false }
    const conversation = currentConversation.value!
    const dto = conversationDtos.get(conversation.id)
    if (!dto) { notify('会话状态尚未加载，请稍后重试'); return false }
    const clientId = uid('message')
    const turn: Turn = { id: uid('turn'), question: content, answers: [] }
    const answer: Answer = { id: uid('run'), text: '', status: 'running', inputTokens: 0, outputTokens: 0 }
    turn.answers.push(answer)
    conversation.turns.push(turn)
    if (dto.subject === '新的对话') {
      try {
        const updated = await apiRequest<ConversationDto>(`/conversations/${conversation.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ subject: content.slice(0, 40), expected_revision: dto.revision }),
        }, { csrf })
        Object.assign(dto, updated)
        conversation.title = updated.subject
      } catch (error) {
        answer.status = 'failed'
        answer.reason = apiMessage(error)
        notify(apiMessage(error))
        return false
      }
    }
    streamController = new AbortController()
    try {
      await apiEventStream(`/conversations/${conversation.id}/messages:stream`, {
        content,
        client_message_id: clientId,
        expected_conversation_revision: dto.revision,
      }, {
        csrf,
        signal: streamController.signal,
        onEvent: ({ event, data }) => {
          const payload = data as Json
          if (event === 'run.created') {
            turn.id = String(payload.turn_id)
            answer.id = String(payload.run_id)
            dto.revision = Number(payload.conversation_revision)
          } else if (event === 'answer.delta') {
            answer.text += String(payload.text || '')
          } else if (event === 'run.completed') {
            answer.status = 'completed'
            answer.id = String(payload.active_answer_id || answer.id)
            turn.activeAnswerId = answer.id
            dto.revision = Number(payload.conversation_revision)
          } else if (event === 'run.failed') {
            answer.status = 'failed'
            answer.reason = String(payload.error || '模型调用失败')
            dto.revision = Number(payload.conversation_revision || dto.revision)
          }
        },
      })
      if (answer.status === 'running') {
        answer.status = 'failed'
        answer.reason = '回复流提前结束，请刷新会话确认最终状态'
      }
      await loadConversations()
      if (state.role === 'admin') {
        await loadBudget()
        await loadUsage()
      }
      return answer.status === 'completed'
    } catch (error) {
      if (answer.status === 'running') {
        answer.status = streamController.signal.aborted ? 'cancelled' : 'failed'
        answer.reason = streamController.signal.aborted ? '你已停止这条回复' : apiMessage(error)
      }
      if (!(error instanceof DOMException && error.name === 'AbortError')) notify(apiMessage(error))
      return false
    } finally { streamController = undefined }
  }

  function retry() { notify('后端尚未开放重试接口，请重新发送问题'); return false }

  async function stop(status: 'failed' | 'cancelled' = 'cancelled', reason = '你已停止这条回复') {
    const id = runningId.value
    const answer = state.conversations.flatMap(item => item.turns).flatMap(turn => turn.answers).find(item => item.id === id)
    if (answer) { answer.status = status; answer.reason = reason }
    if (id) {
      try { await apiRequest(`/runs/${id}/cancel`, { method: 'POST' }, { csrf, idempotency: true }) }
      catch (error) { if (!(error instanceof ApiError && error.status === 404)) notify(apiMessage(error)) }
    }
    streamController?.abort()
  }

  function setRole(role: Role | null) { if (role === null) void logout() }

  async function setService(enabled: boolean) {
    if (state.role !== 'admin') return false
    try {
      const result = await apiRequest<{ mode: string; authorization_epoch: number }>('/service-mode', {
        method: 'PUT',
        body: JSON.stringify({ mode: enabled ? 'open' : 'service_closed', expected_epoch: serviceEpoch, reason: enabled ? null : '管理员在前端暂停自动回复' }),
      }, { csrf })
      serviceEpoch = result.authorization_epoch
      state.serviceEnabled = result.mode === 'open'
      if (!enabled) await stop('cancelled', '管理员暂停了自动回复')
      notify(enabled ? '自动回复已恢复' : '自动回复已暂停')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function removeConversation(id: string) {
    const dto = conversationDtos.get(id)
    if (!dto) return false
    try {
      await apiRequest(`/conversations/${id}?expected_conversation_revision=${dto.revision}`, { method: 'DELETE' }, { csrf, idempotency: true })
      state.conversations = state.conversations.filter(item => item.id !== id)
      conversationDtos.delete(id)
      if (state.selectedId === id) state.selectedId = state.conversations[0]?.id || ''
      await loadJobs()
      notify('删除请求已受理，可在任务中心查看清理进度')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  function exportConversations() { notify('后端当前版本尚未开放会话导出接口'); return false }
  function downloadPayload() { notify('当前没有可下载的导出产物'); return undefined }

  async function saveConnection(connection: Omit<Connection, 'tested'>) {
    if (state.role !== 'admin') return false
    const deployment = {
      model_id: connection.model.trim(),
      currency: (connection.currency || 'CNY').toUpperCase(),
      input_price_per_million: String(connection.inputPrice ?? 0),
      output_price_per_million: String(connection.outputPrice ?? 0),
      max_input_tokens: Number(connection.maxInputTokens || 4000),
      max_output_tokens: Number(connection.maxOutputTokens || 1200),
    }
    try {
      if (connectionDto) {
        const current = connectionDto.deployments[0]
        const patch: Json = { expected_revision: connectionDto.revision }
        if (connection.name.trim() !== connectionDto.name) patch.name = connection.name.trim()
        if (connection.baseUrl.trim() !== connectionDto.base_url) patch.base_url = connection.baseUrl.trim()
        if (connection.secret?.trim()) patch.secret = connection.secret.trim()
        if (!current || current.model_id !== deployment.model_id || current.currency !== deployment.currency ||
          Number(current.input_price_per_million) !== Number(deployment.input_price_per_million) ||
          Number(current.output_price_per_million) !== Number(deployment.output_price_per_million) ||
          current.max_input_tokens !== deployment.max_input_tokens || current.max_output_tokens !== deployment.max_output_tokens) {
          patch.deployments = [deployment]
        }
        if (Object.keys(patch).length === 1) return true
        connectionDto = await apiRequest<ConnectionDto>(`/provider-connections/${connectionDto.id}`, {
          method: 'PATCH',
          body: JSON.stringify(patch),
        }, { csrf })
      } else {
        if (!connection.secret?.trim()) { notify('首次创建连接必须填写 API Key'); return false }
        connectionDto = await apiRequest<ConnectionDto>('/provider-connections', {
          method: 'POST',
          body: JSON.stringify({ name: connection.name.trim(), provider: 'openai_compatible', base_url: connection.baseUrl.trim(), secret: connection.secret.trim(), deployments: [deployment] }),
        }, { csrf })
      }
      await loadConnection()
      notify('模型连接已保存，请运行真实连接测试')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  function beginConnectionTest() { return undefined }
  function completeConnectionTest() { return false }
  function cancelConnectionTest() { /* live tests are server jobs */ }

  async function testConnection() {
    if (!connectionDto) { notify('请先保存模型连接'); return false }
    try {
      const queued = await apiRequest<{ job_id: string }> (`/provider-connections/${connectionDto.id}/test`, {
        method: 'POST', body: JSON.stringify({ expected_revision: connectionDto.revision }),
      }, { csrf, idempotency: true })
      notify('真实连接测试已提交')
      for (let index = 0; index < 20; index++) {
        await new Promise(resolve => setTimeout(resolve, 500))
        const job = await apiRequest<{ status: string; error_code: string | null }>(`/jobs/${queued.job_id}`)
        if (job.status === 'completed') {
          await Promise.all([loadConnection(), loadJobs(), loadBudget()])
          await loadUsage()
          notify('真实连接测试通过')
          return true
        }
        if (job.status === 'failed' || job.status === 'blocked') {
          await Promise.all([loadJobs(), loadBudget()])
          await loadUsage()
          notify(`连接测试未通过${job.error_code ? `：${job.error_code}` : ''}`)
          return false
        }
      }
      await loadJobs()
      notify('连接测试仍在队列中，请确认后端 Worker 正在运行')
      return false
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function saveBudget(daily: number, monthly: number) {
    if (state.role !== 'admin') return false
    if (!Number.isFinite(daily) || !Number.isFinite(monthly) || daily <= 0 || monthly < daily) { notify('请输入有效额度，月额度应不小于日额度'); return false }
    try {
      budget = await apiRequest<BudgetDto>('/budget-policies/current', {
        method: 'PUT',
        body: JSON.stringify({
          expected_revision: budget?.version || 0,
          currency: budget?.currency || state.connection.currency || 'CNY',
          workspace_daily_limit: daily.toFixed(2),
          workspace_monthly_limit: monthly.toFixed(2),
          conversation_limit: budget?.conversation_limit || Math.min(daily, 10).toFixed(2),
          turn_limit: budget?.turn_limit || Math.min(daily, 2).toFixed(2),
          max_attempts_per_turn: budget?.max_attempts_per_turn || 3,
          max_input_tokens: budget?.max_input_tokens || state.connection.maxInputTokens || 4000,
          max_output_tokens: budget?.max_output_tokens || state.connection.maxOutputTokens || 1200,
          reason: '管理员通过前端更新预算策略',
        }),
      }, { csrf })
      state.dailyLimitCents = cents(budget.workspace_daily_limit)
      state.monthlyLimitCents = cents(budget.workspace_monthly_limit)
      notify('预算策略已更新')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function saveAssistant(name: string, description: string, prompt: string) {
    if (state.role !== 'admin') return false
    if (!connectionDto?.deployments[0]) { notify('请先保存模型连接'); return false }
    if (!budget) { notify('请先配置预算策略'); return false }
    try {
      if (!assistant) {
        assistant = await apiRequest<AssistantDto>('/assistants', { method: 'POST', body: JSON.stringify({ name: name.trim(), description: description.trim() || null }) }, { csrf })
      } else {
        assistant = await apiRequest<AssistantDto>(`/assistants/${assistant.id}`, {
          method: 'PATCH', body: JSON.stringify({ expected_revision: assistant.revision, name: name.trim(), description: description.trim() || null }),
        }, { csrf })
      }
      await apiRequest<VersionDto>(`/assistants/${assistant.id}/versions`, {
        method: 'POST', body: JSON.stringify({ deployment_id: connectionDto.deployments[0].id, prompt: prompt.trim(), policy_version: budget.version }),
      }, { csrf })
      await loadAssistants()
      notify('助手配置已保存为草稿版本')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function activateVersion(id: string) {
    if (!assistant) return false
    const version = state.versions.find(item => item.id === id)
    if (!version?.revision) return false
    try {
      await apiRequest(`/assistant-versions/${id}/activate`, {
        method: 'POST', body: JSON.stringify({ expected_revision: version.revision, reason: '管理员通过前端启用版本' }),
      }, { csrf })
      assistant = await apiRequest<AssistantDto>(`/assistants/${assistant.id}/default-version`, {
        method: 'PUT', body: JSON.stringify({ expected_revision: assistant.revision, version_id: id, reason: '管理员通过前端设置默认版本' }),
      }, { csrf })
      await loadAssistants()
      notify('助手版本已启用并设为默认版本')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function revokeVersion(id: string) {
    const version = state.versions.find(item => item.id === id)
    if (!version?.revision) return false
    try {
      await apiRequest(`/assistant-versions/${id}/revoke`, {
        method: 'POST', body: JSON.stringify({ expected_revision: version.revision, reason: '管理员通过前端停用版本' }),
      }, { csrf })
      await loadAssistants()
      notify('助手版本已停用')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  async function saveWorkspace(name: string) {
    try {
      const data = await apiRequest<{ name: string; revision: number }>('/workspace', {
        method: 'PATCH', body: JSON.stringify({ name: name.trim(), expected_revision: workspaceRevision }),
      }, { csrf })
      state.workspaceName = data.name
      workspaceRevision = data.revision
      notify('工作空间名称已更新')
      return true
    } catch (error) { notify(apiMessage(error)); return false }
  }

  function dispose() { clearTimeout(toastTimer); streamController?.abort() }

  return {
    state, runningId, visibleConversations, currentConversation, usageTotals, availableCents, activeVersion,
    notify, initialize, login, logout, newConversation, selectConversation, startReason, send, retry, stop,
    setRole, setService, removeConversation, exportConversations, downloadPayload, saveConnection,
    beginConnectionTest, completeConnectionTest, cancelConnectionTest, testConnection, saveBudget,
    saveAssistant, activateVersion, revokeVersion, saveWorkspace, dispose,
  }
}
