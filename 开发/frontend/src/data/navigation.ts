export const navigation = [
  { path: '/overview', title: '工作空间概览', icon: 'overview', section: '工作台', admin: true, keywords: '首页 统计 dashboard' },
  { path: '/chat', title: '对话工作台', icon: 'chat', section: '工作台', keywords: '聊天 消息 chat' },
  { path: '/history', title: '会话记录', icon: 'history', section: '工作台', keywords: '历史 搜索 导出 history' },
  { path: '/assistant', title: '助手配置', icon: 'bot', section: '管理', admin: true, keywords: '提示词 版本 prompt' },
  { path: '/connections', title: '模型连接', icon: 'plug', section: '管理', admin: true, keywords: 'API 供应商 model' },
  { path: '/usage', title: '用量与预算', icon: 'chart', section: '管理', admin: true, keywords: '费用 成本 额度 token' },
  { path: '/tasks', title: '任务中心', icon: 'tasks', section: '管理', admin: true, keywords: '下载 导出 删除 job' },
  { path: '/settings', title: '工作空间设置', icon: 'settings', section: '管理', admin: true, keywords: '名称 身份 暂停' },
]

export const starterPrompts = [
  { icon: 'file', title: '整理产品说明', text: '把复杂的说明，变成清楚的步骤', prompt: '帮我把产品说明整理成清楚易懂的客服回复。' },
  { icon: 'chat', title: '优化客服回复', text: '让回答更自然，也更有帮助', prompt: '客户的问题暂时没有可靠资料，应该怎样回复？' },
  { icon: 'chart', title: '了解调用成本', text: '把每一次调用的花费看清楚', prompt: '如何控制 AI 客服的 Token 成本和调用预算？' },
]
