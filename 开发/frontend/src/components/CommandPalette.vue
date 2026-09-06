<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppModal from './AppModal.vue'
import AppIcon from './AppIcon.vue'
import { navigation } from '../data/navigation'
import { workspace } from '../stores/workspace'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const router = useRouter()
const query = ref('')
const selected = ref(0)
const input = ref<HTMLInputElement>()
const results = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const pages = [...navigation, { path: '/modules', title: '功能规划', icon: 'layers', keywords: '知识库 人工客服 训练 演进', admin: false }].filter(item => (!item.admin || workspace.state.role === 'admin') &&
    `${item.title} ${item.keywords}`.toLowerCase().includes(needle))
    .map(item => ({ id: item.path, title: item.title, icon: item.icon, type: '页面', path: item.path }))
  const conversations = workspace.visibleConversations.value.filter(item => item.title.toLowerCase().includes(needle))
    .slice(0, 6).map(item => ({ id: item.id, title: item.title, icon: 'chat', type: '会话', path: '/chat' }))
  return [...pages, ...conversations]
})
watch(() => props.open, async open => {
  if (open) { query.value = ''; selected.value = 0; await nextTick(); input.value?.focus() }
})
watch(query, () => { selected.value = 0 })
async function choose(index: number) {
  const result = results.value[index]
  if (!result) return
  if (result.type === '会话') workspace.selectConversation(result.id)
  emit('close')
  await router.push(result.path)
}
function move(delta: number) {
  if (!results.value.length) return
  selected.value = (selected.value + delta + results.value.length) % results.value.length
  document.getElementById(`command-option-${selected.value}`)?.scrollIntoView({ block: 'nearest' })
}
</script>
<template>
  <AppModal :open="open" title="快捷导航" class="command-modal" @close="emit('close')">
    <div class="command-input"><AppIcon name="search" :size="20" /><input ref="input" v-model="query" aria-label="搜索页面与会话" role="combobox" aria-autocomplete="list" aria-controls="command-results" :aria-expanded="open" :aria-activedescendant="results.length ? `command-option-${selected}` : undefined" placeholder="搜索页面、功能或会话…" autocomplete="off" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)" @keydown.enter.prevent="choose(selected)" /><kbd>ESC</kbd></div>
    <div id="command-results" class="command-results" role="listbox" aria-label="搜索结果">
      <div v-for="(item, index) in results" :id="`command-option-${index}`" :key="item.id" class="command-option" role="option" :aria-selected="selected === index" @click="choose(index)" @mousemove="selected = index"><span class="command-icon"><AppIcon :name="item.icon" :size="18" /></span><span>{{ item.title }}<small>{{ item.type }}</small></span><AppIcon v-if="selected === index" name="enter" :size="15" /></div>
    </div>
    <div v-if="!results.length" class="command-empty"><AppIcon name="search" :size="28" /><strong>没有找到相关结果</strong><p>试试“预算”“模型”或会话标题。</p></div>
    <div class="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>↵</kbd> 打开</span><span>仅搜索当前身份可访问的内容</span></div>
  </AppModal>
</template>
