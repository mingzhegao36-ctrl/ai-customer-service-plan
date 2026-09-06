import type { Turn, UsageEntry } from '../types'

export const money = (cents: number) => '¥' + (cents / 100).toFixed(2)
export const estimateTokens = (text: string) => Math.ceil(text.length / 2)
export function totals(entries: UsageEntry[]) {
  return entries.reduce((sum, entry) => ({
    spent: sum.spent + entry.costCents,
    held: sum.held + entry.heldCents,
    tokens: sum.tokens + entry.tokens,
  }), { spent: 0, held: 0, tokens: 0 })
}
export function retryReason(turn: Turn | undefined, isLast: boolean, hasRunning: boolean): string {
  if (!turn || !isLast) return '仅支持重新生成最后一轮'
  if (hasRunning) return '请等待当前回复结束'
  if (turn.answers.length >= 3) return '本轮已达到 3 次演示调用上限'
  const tokens = turn.answers.reduce((sum, a) => sum + a.inputTokens + a.outputTokens, 0)
  if (tokens >= 24000) return '本轮累计 Token 已达上限'
  return ''
}
export function answerText(question: string, retry: boolean): string {
  const intro = retry ? '我们换一种更简明的方式整理：\n\n' : ''
  if (/成本|费用|预算|token/i.test(question)) {
    return intro + '控制调用成本，可以先从这四件事做起：\n\n1. 为每次提问、每位使用者和工作空间设置额度。\n2. 只携带必要的近期对话与有效摘要，避免重复发送全部历史。\n3. 把重试、摘要和审核一并计入费用。\n4. 对结果未知的调用保留预留费用，核对后再结算。\n\n你可以到“用量与预算”查看示例账本和额度设置。\n\n以上是本地预设回复，用于体验交互，未调用真实 AI。'
  }
  if (/删除|隐私|保存|数据/.test(question)) {
    return intro + '对话数据需要有清楚的保存和删除边界。\n\n• 保存对话不代表同意将它用于训练。\n• 删除应停止后续读取，并逐项跟踪相关副本。\n• “已受理”与“所有副本已清理”是不同状态。\n• 恢复旧备份前，需要重新应用完整删除记录。\n\n本页面仅演示会话操作；刷新后，本次输入与修改会重置。正式持久化和删除协议需要服务端支持。'
  }
  return intro + '可以。建议先把客户的问题整理成一个清晰、可核实的回复。\n\n先确认诉求\n用一句话复述客户希望完成的事情，必要时只追问一个关键信息。\n\n再给出步骤\n优先引用已确认的产品资料，按实际操作顺序说明，并告诉客户完成后应看到什么。\n\n最后留下兜底\n没有可靠依据时，直接说明需要核实，并提供真实可用的人工渠道，不承诺未经确认的结果。\n\n这是用于页面体验的预设示例。真实模型与知识库尚未接入。'
}

