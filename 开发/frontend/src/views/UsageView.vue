<script setup lang="ts">
import { computed, ref } from 'vue'
import PageHeading from '../components/PageHeading.vue'
import AppIcon from '../components/AppIcon.vue'
import { workspace } from '../stores/workspace'
import { money } from '../domain/rules'
const { state, usageTotals, availableCents } = workspace
const daily = ref(state.dailyLimitCents / 100)
const monthly = ref(state.monthlyLimitCents / 100)
const filter = ref('all')
const entries = computed(() => state.usage.filter(u => filter.value === 'all' || u.status === filter.value))
const percent = computed(() => state.dailyLimitCents ? Math.min(100, (usageTotals.value.spent + usageTotals.value.held) / state.dailyLimitCents * 100) : 0)
function statusLabel(status: 'actual' | 'unknown' | 'running') { return status === 'actual' ? (state.mode === 'demo' ? '已确认 · 示例' : '已确认') : status === 'unknown' ? '待核对' : '进行中' }
async function saveBudget() { await workspace.saveBudget(Number(daily.value), Number(monthly.value)) }
</script>
<template>
  <PageHeading title="用量与预算" subtitle="把消费、预留与剩余额度放在一起看。" eyebrow="USAGE & BUDGET"><span class="badge">{{ state.mode === 'demo' ? '本地示例账本' : '服务端预算账本' }}</span></PageHeading>
  <div class="stat-grid">
    <section class="card stat-card"><div class="stat-label">已确认消费<AppIcon name="chart" /></div><div class="stat-value">{{ money(usageTotals.spent) }}</div><p class="stat-caption">{{ state.mode === 'demo' ? '演示金额，无真实扣费' : '当前工作空间日账本' }}</p></section>
    <section class="card stat-card"><div class="stat-label">待核对与进行中预留<AppIcon name="clock" /></div><div class="stat-value">{{ money(usageTotals.held) }}</div><p class="stat-caption">中断后保留，避免提前释放额度</p></section>
    <section class="card stat-card"><div class="stat-label">可用额度<AppIcon name="shield" /></div><div class="stat-value text-green">{{ money(availableCents) }}</div><p class="stat-caption">取日／月限制中较小值后扣减</p></section>
    <section class="card stat-card"><div class="stat-label">记录 Token<AppIcon name="layers" /></div><div class="stat-value">{{ usageTotals.tokens.toLocaleString() }}</div><p class="stat-caption">{{ state.mode === 'demo' ? '含固定样例及本地字符估算' : '供应商已回传的调用用量' }}</p></section>
  </div>
  <div class="two-column-layout">
    <section class="card table-card"><div class="card-header"><div><h2>调用明细</h2><p>{{ state.mode === 'demo' ? '示例账本随本页聊天交互更新' : '服务端记录的模型调用与结算状态' }}</p></div><select v-model="filter" class="filter-select" aria-label="费用状态"><option value="all">全部状态</option><option value="actual">已确认</option><option value="unknown">待核对</option><option value="running">进行中</option></select></div>
      <div class="table-wrap"><table><thead><tr><th>调用记录</th><th>Token</th><th>消费／预留</th><th>状态</th></tr></thead><tbody><tr v-for="entry in entries" :key="entry.id"><td><strong class="ledger-title">{{ entry.label }}</strong><small class="block muted">{{ entry.time }}</small></td><td class="tabular">{{ entry.tokens.toLocaleString() }}</td><td class="tabular">{{ money(entry.status === 'actual' ? entry.costCents : entry.heldCents) }}</td><td><span class="badge" :class="entry.status === 'actual' ? 'green' : 'orange'">{{ statusLabel(entry.status) }}</span></td></tr><tr v-if="!entries.length"><td colspan="4">该状态下暂无记录。</td></tr></tbody></table></div>
      <div class="table-footer">{{ state.mode === 'demo' ? '全部记录为当前页面示例；金额不代表供应商报价。' : 'Token 来自供应商回传；金额汇总来自服务端预算账户。' }}</div>
    </section>
    <div class="stack"><section class="card"><div class="card-header"><h2>预算控制</h2><AppIcon name="sliders" /></div><form class="card-body" @submit.prevent="saveBudget"><div class="metric-line"><span>{{ state.mode === 'demo' ? '演示日额度占用' : '日额度占用' }}</span><strong>{{ percent.toFixed(1) }}%</strong></div><div class="progress-track budget-track"><div class="progress-fill" :style="{ width: percent + '%' }"></div></div><label class="form-field"><span>每日上限（元）</span><input v-model="daily" aria-label="每日上限（元）" class="input" type="number" min="0.01" max="1000000" step="0.01" required /></label><label class="form-field"><span>每月上限（元）</span><input v-model="monthly" aria-label="每月上限（元）" class="input" type="number" min="0.01" max="1000000" step="0.01" required /></label><button class="button primary full" type="submit">{{ state.mode === 'demo' ? '保存演示额度' : '保存预算策略' }}</button></form></section><div class="note"><AppIcon name="shield" :size="16" /><span>{{ state.mode === 'demo' ? '这里仅演示页面状态，不具备实际防超支能力。' : '后端会按工作空间、会话和单轮原子预留预算；结果未知时保留预留等待核对。' }}</span></div></div>
  </div>
</template>
