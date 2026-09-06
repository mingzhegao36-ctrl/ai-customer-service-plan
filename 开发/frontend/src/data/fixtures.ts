import type { Conversation, UsageEntry, DemoJob } from '../types'

export function initialConversations(): Conversation[] {
  return [
    { id: 'welcome', title: '新的对话', owner: 'admin', updatedAt: '今天', turns: [] },
    { id: 'sample-guide', title: '整理产品使用说明', owner: 'admin', updatedAt: '今天 10:24', turns: [{
      id: 'turn-guide', question: '如何把产品说明整理成更容易理解的客服回复？',
      activeAnswerId: 'answer-guide', answers: [{
        id: 'answer-guide', status: 'completed', inputTokens: 286, outputTokens: 174,
        text: '可以从客户正在完成的任务出发，而不是从功能清单出发。\n\n1. 先确认目的：客户现在想完成什么？\n2. 给出最短路径：每一步只描述一个操作。\n3. 说明结果：操作完成后，客户应该看到什么。\n4. 留出兜底：遇到异常时，提供真实可用的人工渠道。\n\n如果你提供一段产品说明，我们可以用这个结构继续整理。\n\n这是一条预设示例回复，尚未调用模型或检索真实知识库。',
      }],
    }] },
    { id: 'sample-policy', title: '优化售后回复的表达', owner: 'admin', updatedAt: '昨天 16:38', turns: [{
      id: 'turn-policy', question: '客户询问退换政策，但暂时没有可用资料。',
      activeAnswerId: 'answer-policy', answers: [{
        id: 'answer-policy', status: 'completed', inputTokens: 241, outputTokens: 92,
        text: '可以这样回复：\n\n“我理解你想确认退换的具体条件。目前这部分信息还需要核实，为了给你准确的答复，我可以协助你联系人工客服。”\n\n回复应以实际政策为依据，不直接承诺退款、时限或资格。这是前端预设内容，人工渠道尚未接入。',
      }],
    }] },
    { id: 'member-welcome', title: '我的第一条对话', owner: 'member', updatedAt: '今天', turns: [] },
  ]
}

export function initialUsage(): UsageEntry[] {
  return [
    { id: 'seed-1', label: '整理产品使用说明', status: 'actual', tokens: 12480, costCents: 286, heldCents: 0, time: '10:24' },
    { id: 'seed-2', label: '优化售后回复的表达', status: 'actual', tokens: 8630, costCents: 194, heldCents: 0, time: '09:48' },
    { id: 'seed-3', label: '常见问题内部验证', status: 'actual', tokens: 15120, costCents: 302, heldCents: 0, time: '09:12' },
    { id: 'seed-4', label: '中断调用待核对', status: 'unknown', tokens: 960, costCents: 0, heldCents: 24, time: '08:56' },
  ]
}

export function initialJobs(): DemoJob[] {
  return [
    { id: 'job-sample-export', title: '会话数据导出示例', type: 'export', status: 'completed', createdAt: '今天 10:30', detail: '仅含预设测试资料的 JSON 示例文件。', payload: JSON.stringify({ demo: true, source: '预设测试资料', conversations: [] }, null, 2) },
    { id: 'job-sample-review', title: '中断调用费用核对', type: 'reconcile', status: 'blocked', createdAt: '今天 08:56', detail: '等待供应商用量记录。此处演示“待核对”状态，不自动释放预留费用。' },
  ]
}

