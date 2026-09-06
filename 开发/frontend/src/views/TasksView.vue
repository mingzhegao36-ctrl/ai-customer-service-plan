<script setup lang="ts">
import { computed, ref } from 'vue'
import PageHeading from '../components/PageHeading.vue'
import AppIcon from '../components/AppIcon.vue'
import AppModal from '../components/AppModal.vue'
import { workspace } from '../stores/workspace'
import type { DemoJob } from '../types'
const filter = ref('all')
const selected = ref<DemoJob>()
const jobs = computed(() => workspace.state.jobs.filter(j => filter.value === 'all' || j.status === filter.value))
const labels: Record<DemoJob['status'], string> = { queued: '排队中', running: '处理中', completed: '已完成', failed: '失败', blocked: '已阻断' }
const typeLabels: Record<DemoJob['type'], string> = { export: '会话导出', delete: '会话删除', reconcile: '费用核对', provider_test: '连接测试' }
function statusLabel(status: DemoJob['status']) { return workspace.state.mode === 'demo' ? ({ queued: '准备中', running: '处理中', completed: '示例已完成', failed: '失败', blocked: '已阻断' } as Record<DemoJob['status'], string>)[status] : labels[status] }
function download(id: string) {
  const payload = workspace.downloadPayload(id)
  if (!payload) return
  const url = URL.createObjectURL(new Blob([payload], { type: 'application/json;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = '知应-示例会话-' + id + '.json'; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>
<template>
  <PageHeading title="任务中心" subtitle="追踪后台操作并查看处理结果。" eyebrow="BACKGROUND TASKS"><RouterLink v-if="workspace.state.mode === 'demo'" class="button primary" to="/history"><AppIcon name="plus" :size="15" />从会话发起导出</RouterLink></PageHeading>
  <div class="filter-bar"><div class="tabs" aria-label="任务筛选"><button v-for="item in [{ id: 'all', title: '全部任务' }, { id: 'queued', title: '准备中' }, { id: 'completed', title: '已完成' }, { id: 'blocked', title: '已阻断' }]" :key="item.id" class="tab" :class="{ active: filter === item.id }" :aria-pressed="filter === item.id" @click="filter = item.id">{{ item.title }}</button></div><span class="filter-spacer"></span><span class="muted">{{ jobs.length }} 条任务</span></div>
  <section class="card table-card"><div class="table-wrap"><table><thead><tr><th>任务</th><th>类型</th><th>创建时间</th><th>状态</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="job in jobs" :key="job.id"><td><div class="table-cell-title"><span class="row-icon"><AppIcon :name="job.type === 'export' ? 'download' : job.type === 'delete' ? 'trash' : job.type === 'provider_test' ? 'plug' : 'clock'" :size="17" /></span><span>{{ job.title }}<small>{{ job.id }}</small></span></div></td><td>{{ typeLabels[job.type] }}</td><td>{{ job.createdAt }}</td><td><span class="badge" :class="job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : 'orange'">{{ statusLabel(job.status) }}</span></td><td><div class="row-actions"><button class="text-button" @click="selected = job">详情</button><button v-if="workspace.state.mode === 'demo' && job.type === 'export' && job.status === 'completed'" class="button small" @click="download(job.id)"><AppIcon name="download" :size="13" />下载示例</button></div></td></tr><tr v-if="!jobs.length"><td colspan="5">该状态下暂无任务。</td></tr></tbody></table></div><div class="table-footer">{{ workspace.state.mode === 'demo' ? '刷新页面会重置演示任务。' : '状态由后端持久任务与 Worker 实际处理结果提供。' }}</div></section>
  <AppModal :open="!!selected" title="任务详情" :description="selected?.detail" @close="selected = undefined"><p class="muted">状态：{{ selected ? statusLabel(selected.status) : '' }}</p><div class="form-actions"><button class="button" @click="selected = undefined">关闭</button></div></AppModal>
</template>
