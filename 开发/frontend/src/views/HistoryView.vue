<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import AppModal from '../components/AppModal.vue'
import PageHeading from '../components/PageHeading.vue'
import EmptyState from '../components/EmptyState.vue'
import { workspace } from '../stores/workspace'
import type { Conversation } from '../types'
const router = useRouter()
const { state, visibleConversations } = workspace
const search = ref('')
const filter = ref('all')
const page = ref(1)
const selected = ref<string[]>([])
const removeId = ref('')
const pageSize = 6
function status(c: Conversation) {
  const last = c.turns.at(-1)?.answers.at(-1)
  return !last ? 'empty' : last.status === 'completed' ? 'completed' : last.status === 'running' ? 'running' : 'incomplete'
}
const filtered = computed(() => visibleConversations.value.filter(c => c.title.toLowerCase().includes(search.value.trim().toLowerCase()) && (filter.value === 'all' || status(c) === filter.value)))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const rows = computed(() => filtered.value.slice((Math.min(page.value, pages.value) - 1) * pageSize, Math.min(page.value, pages.value) * pageSize))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every(c => selected.value.includes(c.id)))
function selectAll() { selected.value = allSelected.value ? selected.value.filter(id => !rows.value.some(c => c.id === id)) : [...new Set([...selected.value, ...rows.value.map(c => c.id)])] }
function open(c: Conversation) { workspace.selectConversation(c.id); void router.push('/chat') }
async function newChat() { if (await workspace.newConversation()) await router.push('/chat') }
async function remove() { if (await workspace.removeConversation(removeId.value)) selected.value = selected.value.filter(id => id !== removeId.value); removeId.value = '' }
function exportSelected() { if (workspace.exportConversations(selected.value)) { selected.value = []; void router.push('/tasks') } }
const labels: Record<string,string> = { completed: '已完成', running: '回复中', incomplete: '未完成', empty: '新会话' }
</script>
<template>
  <PageHeading title="会话记录" subtitle="每一段交流都可追溯，找到需要继续的对话。" eyebrow="CONVERSATION HISTORY"><button class="button primary" @click="newChat"><AppIcon name="plus" :size="15" />新建对话</button></PageHeading>
  <div class="history-summary"><span class="tag-icon green"><AppIcon name="history" :size="24" /></span><div><strong>{{ visibleConversations.length }} 条{{ state.mode === 'demo' ? '示例' : '' }}会话</strong><p>{{ state.mode === 'demo' ? '当前预览身份可见的会话 · 刷新页面后重置' : '当前账户可见的服务端会话' }}</p></div><span class="badge">{{ state.mode === 'demo' ? '当前页面内存' : '服务端持久化' }}</span></div>
  <div class="filter-bar"><label class="search-field"><AppIcon name="search" :size="15" /><input v-model="search" aria-label="搜索会话" placeholder="搜索会话标题…" @input="page = 1" /></label><select v-model="filter" class="filter-select" aria-label="筛选会话状态" @change="page = 1"><option value="all">全部状态</option><option value="completed">已完成</option><option value="incomplete">未完成</option><option value="empty">新会话</option></select><span class="filter-spacer"></span><button v-if="state.mode === 'demo' && state.role === 'admin'" class="button" :disabled="!selected.length" @click="exportSelected"><AppIcon name="download" :size="14" />导出示例<span v-if="selected.length">({{ selected.length }})</span></button></div>
  <section class="card table-card"><div v-if="rows.length" class="table-wrap"><table><thead><tr><th v-if="state.role === 'admin'" class="checkbox-col"><input type="checkbox" aria-label="选择本页会话" :checked="allSelected" @change="selectAll" /></th><th>会话标题</th><th>助手</th><th>消息</th><th>状态</th><th>最近更新</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="c in rows" :key="c.id"><td v-if="state.role === 'admin'"><input v-model="selected" type="checkbox" :value="c.id" :aria-label="'选择 ' + c.title" /></td><td><button class="table-title-button" @click="open(c)"><span class="row-icon"><AppIcon name="chat" :size="15" /></span><span>{{ c.title }}<small>{{ c.id }}</small></span></button></td><td class="muted">{{ state.assistantName }}</td><td>{{ c.turns.length }} 轮</td><td><span class="badge" :class="{ green: status(c) === 'completed', orange: status(c) === 'incomplete' }">{{ labels[status(c)] }}</span></td><td class="subtle">{{ c.updatedAt }}</td><td><div class="row-actions"><button class="icon-button" :aria-label="'打开 ' + c.title" @click="open(c)"><AppIcon name="external" :size="15" /></button><button class="icon-button" :aria-label="'移除 ' + c.title" @click="removeId = c.id"><AppIcon name="trash" :size="15" /></button></div></td></tr></tbody></table></div><EmptyState v-else title="没有找到相关会话" description="换一个关键词，或者创建一段新的对话。" icon="search"><button class="button small" @click="search = ''; filter = 'all'">清除筛选</button></EmptyState><div class="table-footer"><span>共 {{ filtered.length }} 条记录<span v-if="selected.length"> · 已选 {{ selected.length }} 条</span></span><div class="flex-row"><button class="button small" :disabled="page <= 1" aria-label="上一页" @click="page--">上一页</button><span>{{ Math.min(page, pages) }} / {{ pages }}</span><button class="button small" :disabled="page >= pages" aria-label="下一页" @click="page++">下一页</button></div></div></section>
  <div class="page-bottom-note"><AppIcon name="shield" :size="13" />{{ state.mode === 'demo' ? '当前为交互示例。' : '删除采用服务端幂等请求，并在任务中心追踪清理与凭证状态。' }}</div>
  <AppModal :open="!!removeId" :title="state.mode === 'demo' ? '移除这条示例会话？' : '删除这条会话？'" :description="state.mode === 'demo' ? '这会清除当前页面内存中的该条对话。' : '会话会立即从列表隐藏，服务端将登记删除凭证并异步清理相关副本。'" @close="removeId = ''"><div class="form-actions"><button class="button" @click="removeId = ''">保留会话</button><button class="button danger" @click="remove">{{ state.mode === 'demo' ? '移除示例' : '确认删除' }}</button></div></AppModal>
</template>
