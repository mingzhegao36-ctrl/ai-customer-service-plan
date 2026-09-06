<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import PageHeading from '../components/PageHeading.vue'
import { workspace } from '../stores/workspace'
import { money } from '../domain/rules'
import { starterPrompts } from '../data/navigation'

const router = useRouter()
const { state, visibleConversations, activeVersion, usageTotals, availableCents } = workspace
const measure = ref<'cost' | 'tokens'>('cost')
const selectedEntryId = ref('')
const completedTurns = computed(() => visibleConversations.value.flatMap(c => c.turns).filter(t => t.activeAnswerId).length)
const pendingJobs = computed(() => state.jobs.filter(j => j.status !== 'completed'))
const recent = computed(() => visibleConversations.value.filter(c => c.turns.length).slice(0, 4))
// These are the actual in-memory ledger entries, not invented historical traffic.
const chartEntries = computed(() => state.usage.slice(0, 8).reverse())
const selectedEntry = computed(() => chartEntries.value.find(e => e.id === selectedEntryId.value) ?? chartEntries.value.at(-1))
const maxValue = computed(() => Math.max(1, ...chartEntries.value.map(e => measure.value === 'tokens' ? e.tokens : e.costCents + e.heldCents)))
const budgetPercent = computed(() => state.dailyLimitCents ? Math.min(100, (usageTotals.value.spent + usageTotals.value.held) / state.dailyLimitCents * 100) : 0)
const readiness = computed(() => [
  { title: '模型连接', detail: state.connection.tested ? (state.mode === 'demo' ? '模拟连接已验证' : '真实连接已验证') : '配置待重新测试', icon: 'plug', ready: state.connection.tested, path: '/connections' },
  { title: '客服助手', detail: activeVersion.value ? `${activeVersion.value.id} · 当前启用版本` : '请选择一个有效版本', icon: 'bot', ready: !!activeVersion.value, path: '/assistant' },
  { title: '自动回复', detail: state.serviceEnabled ? (state.mode === 'demo' ? '页面演示已开启' : '服务端已开启') : '已暂停新消息生成', icon: 'chat', ready: state.serviceEnabled, path: '/settings' },
])
const readyCount = computed(() => readiness.value.filter(item => item.ready).length)
function barHeight(cost: number, held: number, tokens: number) {
  return Math.max(2, (measure.value === 'tokens' ? tokens : cost + held) / maxValue.value * 100) + '%'
}
async function startChat(prompt?: string) {
  if (await workspace.newConversation()) await router.push({ path: '/chat', query: prompt ? { prompt } : {} })
}
function openConversation(id: string) { workspace.selectConversation(id); void router.push('/chat') }
</script>
<template>
  <div class="overview-page">
    <PageHeading title="工作空间概览" subtitle="服务的每一步，都清楚可见。" eyebrow="WORKSPACE OVERVIEW">
      <span class="overview-scope"><AppIcon name="activity" :size="14" />{{ state.mode === 'demo' ? '当前页面 · 示例数据' : '实时服务端数据' }}</span>
    </PageHeading>

    <section class="overview-hero">
      <div class="hero-copy"><span class="hero-kicker"><span class="status-dot"></span> YOUR INTELLIGENT WORKSPACE</span><h2>让每一次回应，<br />都更进一步<span>。</span></h2><p>从倾听一个问题开始，连接对话、知识与服务。<br class="desktop-only" />你的 AI 客服工作空间，已准备好与你一起探索。</p><div class="hero-actions"><button class="button primary" @click="startChat()"><AppIcon name="plus" :size="16" />开始一段对话<AppIcon name="arrow" :size="16" /></button><RouterLink class="hero-secondary" to="/modules">探索功能规划<AppIcon name="external" :size="15" /></RouterLink></div></div>
      <div class="hero-orbit-art" aria-hidden="true"><div class="hero-orbit-grid"></div><div class="hero-ring ring-outer"></div><div class="hero-ring ring-inner"></div><div class="hero-globe"><svg viewBox="0 0 180 180" fill="none"><circle cx="90" cy="90" r="84" /><ellipse cx="90" cy="90" rx="42" ry="84" /><ellipse cx="90" cy="90" rx="68" ry="84" /><path d="M10 63C47 79 133 79 170 63M10 117C47 101 133 101 170 117M31 34C61 47 119 47 149 34M31 146C61 133 119 133 149 146M6 90H174M90 6V174" /></svg><span class="globe-core"><AppIcon name="sparkle" :size="39" :stroke="1.2" /></span></div><span class="orbit-beacon beacon-one"></span><span class="orbit-beacon beacon-two"></span><span class="orbit-chip chip-one"><AppIcon name="chat" :size="17" />倾听 · 理解</span><span class="orbit-chip chip-two"><AppIcon name="sparkle" :size="17" />回应 · 连接</span><span class="orbit-coordinate">ZHIYING / AI SUPPORT</span></div>
      <span class="hero-index">01 / START SOMETHING GOOD</span>
    </section>

    <div class="stat-grid overview-stats">
      <RouterLink class="card stat-card" to="/history"><div class="stat-label">会话总数<span class="stat-icon"><AppIcon name="chat" :size="18" /></span></div><div class="stat-value">{{ visibleConversations.length }}<small>条</small></div><div class="stat-bottom"><span>当前身份可见会话</span><AppIcon name="arrow" :size="15" /></div></RouterLink>
      <RouterLink class="card stat-card" to="/history"><div class="stat-label">有效回复<span class="stat-icon mint"><AppIcon name="success" :size="18" /></span></div><div class="stat-value">{{ completedTurns }}<small>轮</small></div><div class="stat-bottom"><span>已完成并保留的答案</span><AppIcon name="arrow" :size="15" /></div></RouterLink>
      <RouterLink class="card stat-card" to="/usage"><div class="stat-label">已确认消费<span class="stat-icon violet"><AppIcon name="chart" :size="18" /></span></div><div class="stat-value">{{ money(usageTotals.spent) }}</div><div class="stat-bottom"><span>{{ state.mode === 'demo' ? '示例账本 · 无真实扣费' : '后端预算账本' }}</span><AppIcon name="arrow" :size="15" /></div></RouterLink>
      <RouterLink class="card stat-card" to="/tasks"><div class="stat-label">待处理任务<span class="stat-icon amber"><AppIcon name="tasks" :size="18" /></span></div><div class="stat-value">{{ pendingJobs.length }}<small>项</small><span v-if="pendingJobs.length" class="stat-inline-status">需要关注</span></div><div class="stat-bottom"><span>准备中与已阻断的任务</span><AppIcon name="arrow" :size="15" /></div></RouterLink>
    </div>

    <div class="overview-columns">
      <section class="card activity-card"><div class="card-header"><div><h2>调用概况<span class="inline-label">{{ state.mode === 'demo' ? '示例' : '实时' }}</span></h2><p>最近 {{ chartEntries.length }} 条调用 · {{ state.mode === 'demo' ? '含当前页面新产生的记录' : '来自服务端用量查询' }}</p></div><div class="tabs" aria-label="调用图表指标"><button class="tab" :class="{ active: measure === 'cost' }" :aria-pressed="measure === 'cost'" @click="measure = 'cost'">费用</button><button class="tab" :class="{ active: measure === 'tokens' }" :aria-pressed="measure === 'tokens'" @click="measure = 'tokens'">Token</button></div></div>
        <div class="activity-chart" :aria-label="measure === 'cost' ? '调用费用图表' : '调用 Token 图表'">
          <div class="chart-y-labels" aria-hidden="true"><span>{{ measure === 'cost' ? money(maxValue) : maxValue.toLocaleString() }}</span><span>{{ measure === 'cost' ? money(Math.round(maxValue / 2)) : Math.round(maxValue / 2).toLocaleString() }}</span><span>0</span></div>
          <div class="chart-plot"><div class="chart-gridlines" aria-hidden="true"><i></i><i></i><i></i></div><div class="chart-bars"><button v-for="entry in chartEntries" :key="entry.id" class="chart-column" :class="{ selected: entry.id === selectedEntry?.id }" :aria-pressed="entry.id === selectedEntry?.id" :aria-label="`${entry.label}，${entry.time}，${measure === 'cost' ? money(entry.costCents + entry.heldCents) : entry.tokens + ' Token'}，${entry.status === 'actual' ? '已确认' : '预留'}`" @click="selectedEntryId = entry.id"><span class="chart-bar" :class="{ held: entry.status !== 'actual' }" :style="{ height: barHeight(entry.costCents, entry.heldCents, entry.tokens) }"><span class="bar-cap"></span></span><span class="chart-x-label">{{ entry.time }}</span></button></div></div>
        </div>
        <div class="chart-legend"><span><i></i>已确认</span><span><i class="held"></i>待核对 / 进行中预留</span><small>点击柱形查看明细</small></div>
        <div v-if="selectedEntry" class="chart-selection" aria-live="polite"><span class="row-icon"><AppIcon :name="selectedEntry.status === 'actual' ? 'check' : 'clock'" :size="16" /></span><div><strong>{{ selectedEntry.label }}</strong><span>{{ selectedEntry.time }} · {{ selectedEntry.status === 'actual' ? '已确认消费' : '预留待核对' }}</span></div><strong class="tabular">{{ measure === 'cost' ? money(selectedEntry.costCents + selectedEntry.heldCents) : selectedEntry.tokens.toLocaleString() + ' Token' }}</strong></div>
      </section>

      <section class="card overview-budget"><div class="card-header"><h2>预算余量</h2><RouterLink class="text-button" to="/usage" aria-label="管理预算">管理<AppIcon name="external" :size="13" /></RouterLink></div><div class="budget-donut" :style="{ '--budget-angle': budgetPercent * 3.6 + 'deg' }" role="img" :aria-label="`日额度已占用 ${budgetPercent.toFixed(1)}%`"><div><span>剩余可用</span><strong>{{ money(availableCents) }}</strong><small>{{ state.mode === 'demo' ? '示例金额' : '预算账本' }} / CNY</small></div></div><div class="budget-breakdown"><div><span><i></i>已确认消费</span><strong>{{ money(usageTotals.spent) }}</strong></div><div><span><i class="held"></i>待核对与进行中</span><strong>{{ money(usageTotals.held) }}</strong></div><div><span>每日额度</span><strong>{{ money(state.dailyLimitCents) }}</strong></div></div><p class="budget-footnote"><AppIcon name="shield" :size="13" />中断调用的预留会继续保留</p></section>

      <section class="card overview-recent"><div class="card-header"><div><h2>继续最近的对话</h2><p>让问题有下文，让服务有延续。</p></div><RouterLink class="text-button" to="/history">全部会话<AppIcon name="arrow" :size="14" /></RouterLink></div><div class="overview-conversations"><button v-for="item in recent" :key="item.id" @click="openConversation(item.id)"><span class="row-icon"><AppIcon name="chat" :size="18" /></span><span class="conversation-list-copy"><strong>{{ item.title }}</strong><small>{{ item.turns.at(-1)?.question }}</small></span><span class="conversation-list-meta">{{ item.updatedAt }}<small>{{ item.turns.length }} 轮对话</small></span><AppIcon name="chevron" :size="16" /></button><div v-if="!recent.length" class="empty-state"><AppIcon name="chat" :size="28" /><p>还没有对话，从你的第一个问题开始。</p><button class="button small" @click="startChat()">新建对话</button></div></div></section>

      <section class="card readiness-card"><div class="card-header"><h2>工作空间状态</h2><span class="badge" :class="readyCount === 3 ? 'green' : 'orange'">{{ readyCount }}/3 已就绪</span></div><div class="readiness-items"><RouterLink v-for="item in readiness" :key="item.path" :to="item.path"><span class="readiness-icon"><AppIcon :name="item.icon" :size="18" /></span><span><strong>{{ item.title }}</strong><small>{{ item.detail }}</small></span><AppIcon :name="item.ready ? 'success' : 'alert'" :class="item.ready ? 'text-green' : 'text-orange'" :size="17" /></RouterLink></div><div class="readiness-footer">{{ state.mode === 'demo' ? '仅表示本地演示配置状态' : '读取当前服务端配置状态' }}</div></section>
    </div>

    <section class="overview-quickstart"><div class="quickstart-title"><span class="eyebrow">A LITTLE INSPIRATION</span><h2>不知道从哪里开始？</h2><p>选一个场景，试着聊聊。</p></div><button v-for="item in starterPrompts" :key="item.title" class="quickstart-item" @click="startChat(item.prompt)"><span class="quickstart-icon"><AppIcon :name="item.icon" :size="21" /></span><span><strong>{{ item.title }}</strong><small>{{ item.text }}</small></span><AppIcon name="external" :size="15" /></button></section>
    <footer class="overview-footer"><span><span class="status-dot"></span>知应 AI · 让服务更有回应</span><span>{{ state.mode === 'demo' ? '前端预览 v0.3 · 数据刷新后重置' : '前后端联调 v0.4 · 服务端持久化' }}</span></footer>
  </div>
</template>
