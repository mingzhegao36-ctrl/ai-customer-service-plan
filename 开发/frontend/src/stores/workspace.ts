import { computed, reactive } from 'vue'
import { initialConversations, initialJobs, initialUsage } from '../data/fixtures'
import { answerText, estimateTokens, retryReason, totals } from '../domain/rules'
import type { AssistantVersion, Connection, ConnectionTestTicket, Conversation, Role, Scenario, Turn } from '../types'
import { createLiveWorkspace } from './liveWorkspace'

const uid = (prefix: string) => prefix + '-' + crypto.randomUUID().slice(0, 8)
const time = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })

export function createDemoWorkspace() {
  const state = reactive({
    mode: 'demo' as 'demo' | 'live',
    apiStatus: 'ready' as 'connecting' | 'ready' | 'offline',
    loading: false,
    authError: '',
    userName: '示例管理员',
    role: 'admin' as Role | null,
    workspaceName: '我的客服工作空间',
    conversations: initialConversations(),
    selectedId: 'welcome',
    usage: initialUsage(),
    jobs: initialJobs(),
    serviceEnabled: true,
    assistantName: '通用客服助手',
    assistantDescription: '清楚回应，认真解决每一个问题。',
    versions: [
      { id: 'v1.2', prompt: '你是一位耐心、准确的内部客服助手。优先依据已确认的信息回答；无依据时明确说明，并给出人工核实建议。', state: 'active', date: '2026-09-05' },
      { id: 'v1.1', prompt: '简明回答产品相关问题，不编造政策或执行结果。', state: 'revoked', date: '2026-09-04' },
    ] as AssistantVersion[],
    connection: { name: '示例模型连接', baseUrl: 'https://api.example.com/v1', model: 'demo-support-model', tested: true } as Connection,
    dailyLimitCents: 2000,
    monthlyLimitCents: 20000,
    scenario: 'normal' as Scenario,
    toast: '',
  })
  let timer: ReturnType<typeof setTimeout> | undefined
  let toastTimer: ReturnType<typeof setTimeout> | undefined
  const jobTimers = new Set<ReturnType<typeof setTimeout>>()
  let connectionRevision = 0
  let testSequence = 0
  let pendingConnectionTest: ConnectionTestTicket | undefined
  const runningId = computed(() => state.conversations.flatMap(c => c.turns).flatMap(t => t.answers).find(a => a.status === 'running')?.id)
  const visibleConversations = computed(() => state.conversations.filter(c => c.owner === state.role))
  const currentConversation = computed(() => visibleConversations.value.find(c => c.id === state.selectedId))
  const usageTotals = computed(() => totals(state.usage))
  const availableCents = computed(() => Math.max(0, Math.min(state.dailyLimitCents, state.monthlyLimitCents) - usageTotals.value.spent - usageTotals.value.held))
  const activeVersion = computed(() => state.versions.find(v => v.state === 'active'))

  function notify(message: string) {
    state.toast = message
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { state.toast = '' }, 3600)
  }
  function newConversation() {
    if (!state.role) return false
    if (runningId.value) stop('cancelled', '已切换会话，本次演示回复已停止')
    const conversation: Conversation = { id: uid('conv'), title: '新的对话', owner: state.role, updatedAt: '刚刚', turns: [] }
    state.conversations.unshift(conversation)
    state.selectedId = conversation.id
    return true
  }
  function selectConversation(id: string) {
    if (!visibleConversations.value.some(c => c.id === id)) return false
    if (runningId.value && id !== state.selectedId) stop('cancelled', '切换会话后停止本次演示回复')
    state.selectedId = id
    return true
  }
  function startReason() {
    if (!state.role) return '请先选择预览身份'
    if (!currentConversation.value) return '请新建一个会话'
    if (runningId.value) return '请等待当前回复结束'
    if (!state.serviceEnabled) return '自动回复已暂停，请联系管理员'
    if (!activeVersion.value) return '当前助手版本已停用'
    if (!state.connection.tested) return '请先在模型连接页完成模拟测试'
    if (state.scenario === 'budget' || availableCents.value < 20) return '当前演示额度不足，请查看用量与预算'
    return ''
  }
  function execute(turn: Turn, retry: boolean) {
    const conversation = currentConversation.value
    if (!conversation) return false
    const usedTokens = turn.answers.reduce((sum, a) => sum + a.inputTokens + a.outputTokens, 0)
    // Approximation for the preview only. Production must count the complete provider request.
    const inputTokens = estimateTokens(conversation.turns.map(t => t.question + (t.answers.find(a => a.id === t.activeAnswerId)?.text ?? '')).join('\n'))
    if (inputTokens > 4000 || usedTokens + inputTokens + 1200 > 24000) { notify('演示上下文已到上限，请新建会话'); return false }
    const id = uid('run')
    turn.answers.push({ id, text: '', status: 'running', inputTokens, outputTokens: 0 })
    state.usage.unshift({ id, label: conversation.title, status: 'running', tokens: inputTokens, costCents: 0, heldCents: 20, time: time() })
    const convId = conversation.id
    const response = answerText(turn.question, retry)
    const scenario = state.scenario
    let offset = 0
    function tick() {
      const conv = state.conversations.find(c => c.id === convId && c.owner === state.role)
      const currentTurn = conv?.turns.find(t => t.id === turn.id)
      const run = currentTurn?.answers.find(a => a.id === id)
      if (!run || !currentTurn || run.status !== 'running') return
      if (!state.serviceEnabled || !activeVersion.value) { stop('cancelled', '自动回复已停用'); return }
      if (scenario === 'disconnect' && offset >= 72) { stop('failed', '网络连接中断，已保留本次可见片段'); return }
      offset = Math.min(offset + 9, response.length)
      run.text = response.slice(0, offset)
      run.outputTokens = estimateTokens(run.text)
      const entry = state.usage.find(u => u.id === id)
      if (entry) entry.tokens = inputTokens + run.outputTokens
      if (offset >= response.length) {
        run.status = 'completed'
        currentTurn.activeAnswerId = id
        if (entry) { entry.status = 'actual'; entry.costCents = Math.max(1, Math.ceil(inputTokens / 1000 + run.outputTokens / 500)); entry.heldCents = 0 }
        conv!.updatedAt = '刚刚'
        timer = undefined
        return
      }
      timer = setTimeout(tick, 32)
    }
    timer = setTimeout(tick, 360)
    return true
  }
  function send(question: string) {
    const reason = startReason()
    if (reason) { notify(reason); return false }
    const trimmed = question.trim()
    if (!trimmed) return false
    if (trimmed.length > 2000) { notify('单条消息最多 2,000 个字符'); return false }
    const conv = currentConversation.value!
    const turn: Turn = { id: uid('turn'), question: trimmed, answers: [] }
    if (!conv.turns.length) conv.title = trimmed.slice(0, 20)
    conv.turns.push(turn)
    const liveTurn = conv.turns[conv.turns.length - 1]!
    const ok = execute(liveTurn, false)
    if (!ok) conv.turns.pop()
    return ok
  }
  function retry(turnId: string) {
    const conv = currentConversation.value
    const turn = conv?.turns.find(t => t.id === turnId)
    const reason = retryReason(turn, conv?.turns.at(-1)?.id === turnId, !!runningId.value) || startReason()
    if (reason) { notify(reason); return false }
    return execute(turn!, true)
  }
  function stop(status: 'failed' | 'cancelled' = 'cancelled', reason = '你已停止这条回复') {
    clearTimeout(timer)
    timer = undefined
    for (const conv of state.conversations) for (const turn of conv.turns) for (const run of turn.answers) {
      if (run.status !== 'running') continue
      run.status = status
      run.reason = reason
      const entry = state.usage.find(u => u.id === run.id)
      if (entry) entry.status = 'unknown'
    }
  }
  function setService(enabled: boolean) {
    if (state.role !== 'admin') return false
    state.serviceEnabled = enabled
    if (!enabled) stop('cancelled', '管理员暂停了自动回复')
    notify(enabled ? '已恢复演示自动回复' : '已暂停演示自动回复；待核对费用仍保留')
    return true
  }
  function setRole(role: Role | null) {
    pendingConnectionTest = undefined
    stop('cancelled', '预览身份已切换')
    state.role = role
    state.userName = role === 'admin' ? '示例管理员' : role === 'member' ? '示例内部使用者' : ''
    state.selectedId = visibleConversations.value[0]?.id ?? ''
  }
  function removeConversation(id: string) {
    const conv = visibleConversations.value.find(c => c.id === id)
    if (!conv) return false
    if (state.selectedId === id) stop('cancelled', '会话示例已移除')
    state.conversations = state.conversations.filter(c => c.id !== id)
    for (const job of state.jobs) if (job.sourceIds?.includes(id)) {
      job.status = 'blocked'; job.payload = undefined; job.detail = '来源会话已移除，示例下载已失效。'
    }
    state.jobs.unshift({ id: uid('job'), title: '移除会话示例', type: 'delete', status: 'completed', createdAt: '刚刚', detail: '只移除了当前页面内存中的示例会话。正式数据删除、独立凭证与副本清理尚未接入。' })
    if (state.selectedId === id) { state.selectedId = visibleConversations.value[0]?.id ?? ''; if (!state.selectedId) newConversation() }
    notify('会话示例已移除')
    return true
  }
  function exportConversations(ids: string[]) {
    if (state.role !== 'admin') { notify('管理导出仅对管理员预览身份开放'); return false }
    const selected = visibleConversations.value.filter(c => ids.includes(c.id))
    if (!selected.length) { notify('请先选择会话'); return false }
    const jobId = uid('export')
    // Capture only the approved effective answer; raw alternative candidates are excluded.
    const payload = JSON.stringify({ demo: true, generatedAt: new Date().toISOString(), conversations: selected.map(c => ({
      id: c.id, title: c.title, turns: c.turns.map(t => ({ question: t.question, answer: t.answers.find(a => a.id === t.activeAnswerId)?.text ?? null })),
    })) }, null, 2)
    state.jobs.unshift({ id: jobId, title: '导出 ' + selected.length + ' 条示例会话', type: 'export', status: 'queued', sourceIds: selected.map(c => c.id), createdAt: '刚刚', detail: '正在准备当前页面示例数据。' })
    const jobTimer = setTimeout(() => {
      jobTimers.delete(jobTimer)
      const job = state.jobs.find(j => j.id === jobId)
      if (!job) return
      if (state.role !== 'admin' || selected.some(c => !state.conversations.some(live => live.id === c.id))) {
        job.status = 'blocked'; job.detail = '来源已移除或身份已切换，示例导出已阻断。'; return
      }
      job.status = 'completed'; job.detail = '示例 JSON 已就绪；仅包含本次选定会话。'; job.payload = payload
      notify('示例导出已就绪，可在任务中心下载')
    }, 700)
    jobTimers.add(jobTimer)
    return true
  }
  function downloadPayload(id: string) {
    const job = state.jobs.find(j => j.id === id)
    if (state.role !== 'admin' || job?.status !== 'completed' || job.type !== 'export' || !job.payload || job.sourceIds?.some(source => !visibleConversations.value.some(c => c.id === source))) {
      notify('当前示例下载不可用'); return undefined
    }
    return job.payload
  }
  function saveConnection(connection: Omit<Connection, 'tested'>) {
    if (state.role !== 'admin') return false
    let url: URL
    try { url = new URL(connection.baseUrl) } catch { notify('请输入有效的 API 地址'); return false }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) { notify('API 地址不能包含凭据、查询参数或片段'); return false }
    if (!connection.name.trim() || !connection.model.trim()) { notify('请填写连接名称和模型标识'); return false }
    connectionRevision++
    pendingConnectionTest = undefined
    state.connection = { name: connection.name.trim(), baseUrl: connection.baseUrl.trim(), model: connection.model.trim(), tested: false }
    notify('示例配置已保存，请进行模拟连接测试')
    return true
  }
  function beginConnectionTest(): ConnectionTestTicket | undefined {
    if (state.role !== 'admin') return undefined
    state.connection.tested = false
    const { name, baseUrl, model } = state.connection
    pendingConnectionTest = Object.freeze({ revision: connectionRevision, sequence: ++testSequence, snapshot: Object.freeze({ name, baseUrl, model }) })
    return pendingConnectionTest
  }
  function completeConnectionTest(ticket: ConnectionTestTicket, succeeded = true) {
    if (state.role !== 'admin' || ticket !== pendingConnectionTest || ticket.revision !== connectionRevision ||
      Object.entries(ticket.snapshot).some(([key, value]) => state.connection[key as keyof Connection] !== value)) return false
    pendingConnectionTest = undefined
    state.connection.tested = succeeded
    notify(succeeded ? '模拟测试通过；未向供应商发送请求' : '模拟测试失败，请检查配置')
    return true
  }
  function cancelConnectionTest(ticket: ConnectionTestTicket) { if (pendingConnectionTest === ticket) pendingConnectionTest = undefined }
  function saveBudget(daily: number, monthly: number) {
    if (state.role !== 'admin') return false
    if (!Number.isFinite(daily) || !Number.isFinite(monthly) || daily <= 0 || monthly < daily || monthly > 1000000) { notify('请输入有效额度：月额度不小于日额度，且不超过 1,000,000 元'); return false }
    state.dailyLimitCents = Math.round(daily * 100)
    state.monthlyLimitCents = Math.round(monthly * 100)
    notify('演示额度已更新，已有费用与预留保持不变')
    return true
  }
  function saveAssistant(name: string, description: string, prompt: string) {
    if (state.role !== 'admin') return false
    if (!name.trim() || !prompt.trim()) { notify('助手名称和提示词不能为空'); return false }
    state.assistantName = name.trim()
    state.assistantDescription = description.trim()
    state.versions.unshift({ id: 'v1.' + (state.versions.length + 1), prompt: prompt.trim(), state: 'draft', date: '刚刚' })
    notify('已保存新的示例草稿；当前生效版本未变')
    return true
  }
  function activateVersion(id: string) {
    if (state.role !== 'admin') return false
    const version = state.versions.find(v => v.id === id)
    if (!version || version.state === 'revoked') return false
    stop('cancelled', '演示助手版本已切换')
    state.versions.forEach(v => { if (v.state === 'active') v.state = 'draft' })
    version.state = 'active'
    notify('示例版本已启用；正式版本迁移仍需服务端实现')
    return true
  }
  function revokeVersion(id: string) {
    if (state.role !== 'admin') return false
    const version = state.versions.find(v => v.id === id)
    if (!version) return false
    version.state = 'revoked'
    stop('cancelled', '助手版本已停用')
    notify('示例版本已停用')
    return true
  }
  function dispose() { clearTimeout(timer); clearTimeout(toastTimer); jobTimers.forEach(clearTimeout); jobTimers.clear(); pendingConnectionTest = undefined }
  async function initialize() { return true }
  async function login(username: string, _password: string, _remember = false) { setRole(username.toLowerCase().includes('member') ? 'member' : 'admin'); return true }
  async function logout() { setRole(null) }
  async function saveWorkspace(name: string) { if (!name.trim()) return false; state.workspaceName = name.trim(); notify('示例名称已更新'); return true }
  async function testConnection() {
    const ticket = beginConnectionTest()
    if (!ticket) return false
    await new Promise(resolve => setTimeout(resolve, 300))
    return completeConnectionTest(ticket)
  }
  return { state, runningId, visibleConversations, currentConversation, usageTotals, availableCents, activeVersion, notify, newConversation, selectConversation, startReason, send, retry, stop, setRole, setService, removeConversation, exportConversations, downloadPayload, saveConnection, beginConnectionTest, completeConnectionTest, cancelConnectionTest, testConnection, saveBudget, saveAssistant, activateVersion, revokeVersion, saveWorkspace, initialize, login, logout, dispose }
}
export const workspace = (import.meta.env.VITE_DEMO_MODE === 'true' ? createDemoWorkspace() : createLiveWorkspace()) as ReturnType<typeof createDemoWorkspace>
