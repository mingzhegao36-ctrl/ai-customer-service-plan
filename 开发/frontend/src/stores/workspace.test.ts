import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDemoWorkspace } from './workspace'
describe('预览状态边界', () => {
  let ws: ReturnType<typeof createDemoWorkspace>
  beforeEach(() => { vi.useFakeTimers(); ws = createDemoWorkspace() })
  afterEach(() => { ws.dispose(); vi.useRealTimers() })
  it('重复发送不会产生第二个生成或重复预留', () => {
    const before = ws.usageTotals.value.held
    expect(ws.send('整理产品说明')).toBe(true)
    expect(ws.send('重复提交')).toBe(false)
    expect(ws.currentConversation.value!.turns).toHaveLength(1)
    expect(ws.usageTotals.value.held).toBe(before + 20)
  })
  it('停止后迟到回调不会恢复生成或释放未知预留', async () => {
    ws.send('测试停止')
    ws.stop()
    await vi.runAllTimersAsync()
    const answer = ws.currentConversation.value!.turns[0].answers[0]
    expect(answer.status).toBe('cancelled')
    expect(answer.text).toBe('')
    expect(ws.state.usage[0].status).toBe('unknown')
    expect(ws.state.usage[0].heldCents).toBe(20)
    expect(ws.currentConversation.value!.turns[0].activeAnswerId).toBeUndefined()
  })
  it('重试失败保留旧有效答案，成功才替换，三次后禁止继续', async () => {
    ws.send('如何控制成本？')
    await vi.runAllTimersAsync()
    const turn = ws.currentConversation.value!.turns[0]
    const old = turn.activeAnswerId
    expect(old).toBeTruthy()
    ws.state.scenario = 'disconnect'
    expect(ws.retry(turn.id)).toBe(true)
    await vi.runAllTimersAsync()
    expect(turn.activeAnswerId).toBe(old)
    expect(turn.answers[1].status).toBe('failed')
    ws.state.scenario = 'normal'
    expect(ws.retry(turn.id)).toBe(true)
    await vi.runAllTimersAsync()
    expect(turn.activeAnswerId).not.toBe(old)
    expect(ws.retry(turn.id)).toBe(false)
    expect(turn.answers).toHaveLength(3)
  })
  it('已出现新一轮时不能重试历史轮次', async () => {
    ws.send('第一轮'); await vi.runAllTimersAsync()
    const first = ws.currentConversation.value!.turns[0].id
    ws.send('第二轮'); await vi.runAllTimersAsync()
    expect(ws.retry(first)).toBe(false)
  })
  it('额度不足不产生消息、调用或预留', () => {
    ws.saveBudget(8, 20)
    const before = ws.state.usage.length
    expect(ws.send('额度不足时提交')).toBe(false)
    expect(ws.state.usage).toHaveLength(before)
    expect(ws.currentConversation.value!.turns).toHaveLength(0)
  })
  it('暂停自动回复后迟到回调不能复活，恢复后才允许新调用', async () => {
    ws.send('正在生成')
    ws.setService(false)
    await vi.runAllTimersAsync()
    expect(ws.runningId.value).toBeUndefined()
    expect(ws.send('暂停中提交')).toBe(false)
    ws.setService(true)
    expect(ws.send('恢复后提交')).toBe(true)
  })
  it.each([0, 800])('来源在 %i ms 后移除，排队及已完成导出均失效', async delay => {
    ws.exportConversations(['sample-guide'])
    const id = ws.state.jobs[0].id
    await vi.advanceTimersByTimeAsync(delay)
    if (delay) expect(ws.downloadPayload(id)).toBeTruthy()
    ws.removeConversation('sample-guide')
    await vi.runAllTimersAsync()
    expect(ws.downloadPayload(id)).toBeUndefined()
    expect(ws.state.jobs.find(j => j.id === id)?.payload).toBeUndefined()
    expect(ws.state.jobs.find(j => j.id === id)?.status).toBe('blocked')
  })
  it('导出只包含有效答案，不把失败候选混入', async () => {
    ws.selectConversation('sample-guide')
    ws.state.scenario = 'disconnect'
    ws.retry('turn-guide')
    await vi.runAllTimersAsync()
    const turn = ws.currentConversation.value!.turns[0]
    ws.exportConversations(['sample-guide'])
    const id = ws.state.jobs[0].id
    await vi.runAllTimersAsync()
    const payload = JSON.parse(ws.downloadPayload(id)!)
    expect(payload.conversations[0].turns[0].answer).toBe(turn.answers[0].text)
    expect(payload.conversations[0].turns[0]).not.toHaveProperty('answers')
  })
  it('普通预览身份不能修改管理员配置或读取管理导出', () => {
    ws.setRole('member')
    expect(ws.visibleConversations.value.every(c => c.owner === 'member')).toBe(true)
    expect(ws.selectConversation('sample-guide')).toBe(false)
    expect(ws.saveBudget(30,300)).toBe(false)
    expect(ws.setService(false)).toBe(false)
    expect(ws.exportConversations(['member-welcome'])).toBe(false)
    expect(ws.downloadPayload('job-sample-export')).toBeUndefined()
    expect(ws.beginConnectionTest()).toBeUndefined()
  })
  it.each([true, false])('旧配置的测试结果 %s 不能污染新保存配置', succeeded => {
    ws.saveConnection({name:'A',baseUrl:'https://a.example.com/v1',model:'demo-a'})
    const first = ws.beginConnectionTest()!
    ws.saveConnection({name:'B',baseUrl:'https://b.example.com/v1',model:'demo-b'})
    expect(ws.completeConnectionTest(first, succeeded)).toBe(false)
    expect(ws.state.connection.tested).toBe(false)
    const next = ws.beginConnectionTest()!
    expect(ws.completeConnectionTest(next)).toBe(true)
    expect(ws.state.connection.baseUrl).toBe('https://b.example.com/v1')
    expect(ws.state.connection.tested).toBe(true)
  })
  it('身份切走再切回，原测试票据仍然无效', () => {
    const ticket = ws.beginConnectionTest()!
    ws.setRole('member'); ws.setRole('admin')
    expect(ws.completeConnectionTest(ticket)).toBe(false)
    expect(ws.state.connection.tested).toBe(false)
  })
  it('取消或组件卸载后的测试结果不可回写', () => {
    const ticket = ws.beginConnectionTest()!
    ws.cancelConnectionTest(ticket)
    expect(ws.completeConnectionTest(ticket)).toBe(false)
    expect(ws.state.connection.tested).toBe(false)
  })
  it('后发测试拥有结果写入权，先发结果不能覆盖它', () => {
    const first = ws.beginConnectionTest()!
    const second = ws.beginConnectionTest()!
    expect(ws.completeConnectionTest(second)).toBe(true)
    expect(ws.completeConnectionTest(first,false)).toBe(false)
    expect(ws.state.connection.tested).toBe(true)
  })
  it('地址不允许携带凭据或查询参数，拒绝时不改变有效配置', () => {
    const before = {...ws.state.connection}
    expect(ws.saveConnection({name:'无效',baseUrl:'https://name:secret@example.com/v1',model:'demo'})).toBe(false)
    expect(ws.saveConnection({name:'无效',baseUrl:'https://example.com/v1?key=placeholder',model:'demo'})).toBe(false)
    expect(ws.state.connection).toEqual(before)
  })
})

