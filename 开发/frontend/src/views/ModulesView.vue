<script setup lang="ts">
import PageHeading from '../components/PageHeading.vue'
import AppIcon from '../components/AppIcon.vue'
import { workspace } from '../stores/workspace'
const modules = [
{ number: '01', icon: 'chat', title: '对话工作台', description: '发送、流式回复、停止与反馈。', path: '/chat', role: '所有登录身份' },
{ number: '02', icon: 'history', title: '会话记录', description: '搜索、筛选、打开与安全删除。', path: '/history', role: '个人会话' },
{ number: '03', icon: 'bot', title: '助手配置', description: '提示词草稿、版本启用与停用。', path: '/assistant', role: '管理员' },
{ number: '04', icon: 'plug', title: '模型连接', description: '连接、部署价格与能力测试。', path: '/connections', role: '管理员' },
{ number: '05', icon: 'chart', title: '用量与预算', description: '消费、预留、Token 与额度策略。', path: '/usage', role: '管理员' },
{ number: '06', icon: 'tasks', title: '任务中心', description: '持久任务状态、阶段与错误详情。', path: '/tasks', role: '管理员' },
{ number: '07', icon: 'settings', title: '工作空间设置', description: '空间名称与自动回复服务状态。', path: '/settings', role: '管理员' },
]
</script>
<template>
  <PageHeading title="功能模块与演进" subtitle="先做好内部对话，再逐步扩展为智能客服。" eyebrow="EXPLORE THE WORKSPACE"><a class="button" href="/space.html">返回星球首页<AppIcon name="external" :size="14" /></a></PageHeading>
  <RouterLink v-if="workspace.state.role === 'admin'" class="module-overview-entry" to="/overview"><span class="tag-icon"><AppIcon name="overview" :size="21" /></span><span><strong>工作空间概览</strong><small>集中查看会话、用量、预算与当前配置状态</small></span><AppIcon name="arrow" :size="18" /></RouterLink>
  <div class="module-intro card"><div><span class="badge green">{{ workspace.state.mode === 'demo' ? '当前 · 前端交互预览' : '当前 · 前后端联调 v0.4' }}</span><h2>一个工作空间，七个核心模块。</h2><p>{{ workspace.state.mode === 'demo' ? '当前使用冻结版本地示例数据。' : 'V1 核心内部工作空间已连接后端；V2 / V3 / V4 仍只展示规划。' }}</p></div><AppIcon name="layers" :size="72" :stroke=".8" /></div>
  <div class="module-grid"><section v-for="(item, index) in modules" :key="item.path" class="card module-card"><div class="flex-row space-between"><span class="tag-icon"><AppIcon :name="item.icon" :size="22" /></span><span class="module-number">{{ item.number }}</span></div><h2>{{ item.title }}</h2><p>{{ item.description }}</p><div class="module-card-footer"><span>{{ item.role }}</span><RouterLink v-if="workspace.state.role === 'admin' || index < 2" :to="item.path" :aria-label="'进入' + item.title"><AppIcon name="arrow" :size="17" /></RouterLink><AppIcon v-else name="lock" :size="14" /></div></section></div>
  <div class="roadmap-band"><div><span>V2</span><h3>知识与客服</h3><p>知识库检索、引用、审核、访客与人工接管。</p></div><div><span>V3</span><h3>业务工具</h3><p>订单查询等受控工具及调用授权。</p></div><div><span>V4</span><h3>训练与微调</h3><p>数据授权、清洗、训练集、评测与灰度。</p></div></div>
  <div class="note"><AppIcon name="alert" :size="16" /><span>{{ workspace.state.mode === 'demo' ? '前端演示通过不代表产品验收通过。' : '当前已接认证、模型调用、持久化、服务端预算及任务协议；生产 PostgreSQL、供应商、恢复和完整 AC／NF 仍需验收。' }}</span></div>
</template>
