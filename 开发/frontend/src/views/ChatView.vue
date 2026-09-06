<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import PageHeading from '../components/PageHeading.vue'
import { workspace } from '../stores/workspace'
import { estimateTokens, money, retryReason } from '../domain/rules'
import type { Answer, Turn } from '../types'
import { starterPrompts as starters } from '../data/navigation'
const router = useRouter()
const route = useRoute()
const { state, currentConversation: conversation, visibleConversations, runningId, activeVersion, availableCents } = workspace
const draft = ref('')
const composer = ref<HTMLTextAreaElement>()
const scrollArea = ref<HTMLElement>()
const stickToBottom = ref(true)
const showInfo = ref(false)
const contextTokens = computed(() => estimateTokens((conversation.value?.turns ?? []).map(t => t.question + (t.answers.find(a => a.id === t.activeAnswerId)?.text ?? '')).join('\n')))
const recent = computed(() => visibleConversations.value.filter(c => c.turns.length > 0).slice(0, 3))
const currentTurns = computed(() => conversation.value?.turns ?? [])
function displayAnswer(turn: Turn): Answer | undefined {
  const latest = turn.answers.at(-1)
  if (latest?.status === 'running') return latest
  return turn.answers.find(a => a.id === turn.activeAnswerId) ?? latest
}
function canRetry(turn: Turn) { return state.mode === 'demo' && !retryReason(turn, currentTurns.value.at(-1)?.id === turn.id, !!runningId.value) && state.serviceEnabled && !!activeVersion.value }
function focusComposer() { composer.value?.focus() }
function useStarter(prompt: string) { draft.value = prompt; void nextTick(focusComposer) }
function send() {
  if (workspace.startReason() || !draft.value.trim()) { void workspace.send(draft.value); return }
  const content = draft.value
  draft.value = ''
  stickToBottom.value = true
  void Promise.resolve(workspace.send(content))
  void scrollBottom()
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); send() }
}
async function scrollBottom() { await nextTick(); if (scrollArea.value) scrollArea.value.scrollTop = scrollArea.value.scrollHeight }
function onScroll() { const el = scrollArea.value; if (el) stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 90 }
async function copy(answer: Answer) {
  try { await navigator.clipboard.writeText((state.mode === 'demo' ? 'AI 示例回复' : 'AI 回复') + '\n\n' + answer.text); workspace.notify('回复已复制，已保留 AI 标识') }
  catch { workspace.notify('复制未成功，请选择文字后手动复制') }
}
async function newChat() { if (await Promise.resolve(workspace.newConversation())) { draft.value = ''; focusComposer() } }
watch(() => currentTurns.value.flatMap(t => t.answers.map(a => a.text)).join(''), () => { if (stickToBottom.value) void scrollBottom() })
watch(() => state.selectedId, () => { draft.value = ''; stickToBottom.value = true; void scrollBottom() })
onBeforeRouteLeave(() => { if (state.mode === 'demo' && runningId.value) workspace.stop('cancelled', '离开对话页后，演示回复已停止') })
onMounted(async () => {
  if (!conversation.value) await Promise.resolve(workspace.newConversation())
  if (typeof route.query.prompt === 'string') {
    draft.value = route.query.prompt.slice(0, 2000)
    await router.replace({ path: '/chat' })
    focusComposer()
  }
})
</script>
<template>
  <div class="chat-page">
    <PageHeading title="对话工作台" subtitle="清楚回应每一个问题，让服务从这里开始。" eyebrow="CONVERSATION WORKSPACE">
      <button class="button" @click="router.push('/history')"><AppIcon name="history" :size="15" />会话记录</button>
      <button class="button primary" @click="newChat"><AppIcon name="plus" :size="15" />新建对话</button>
    </PageHeading>
    <div class="chat-layout">
      <section class="card conversation-card" aria-label="聊天区域">
        <div class="conversation-header"><div class="flex-row"><span class="assistant-avatar"><AppIcon name="bot" :size="23" /></span><div><h2>{{ state.assistantName }}<span class="inline-ai">AI</span></h2><p><span class="status-dot" :class="{ gray: !state.serviceEnabled || !activeVersion }"></span>{{ state.serviceEnabled && activeVersion ? (state.mode === 'demo' ? '可体验 · 本地示例' : '服务可用 · 后端已连接') : '自动回复已暂停' }}<span class="header-separator">/</span>{{ activeVersion?.id ?? '暂无启用版本' }}</p></div></div><div class="flex-row"><button class="icon-button mobile-info-toggle" :aria-expanded="showInfo" aria-label="查看会话概览" @click="showInfo = !showInfo"><AppIcon name="sliders" /></button><RouterLink class="icon-button" to="/modules" aria-label="查看聊天功能说明"><AppIcon name="more" /></RouterLink></div></div>
        <div ref="scrollArea" class="conversation-body" @scroll="onScroll">
          <div v-if="!currentTurns.length" class="welcome-state">
            <div class="welcome-art" aria-hidden="true"><span class="orbit orbit-one"></span><span class="orbit orbit-two"></span><span class="art-dot dot-one"></span><span class="art-dot dot-two"></span><div class="welcome-mark"><AppIcon name="chat" :size="37" :stroke="1.35" /><span class="mark-spark"><AppIcon name="sparkle" :size="16" /></span></div><span class="art-dash"></span></div>
            <span class="welcome-eyebrow">每一次好服务，都从倾听开始</span><h2>你好，有什么可以帮你？</h2><p>从一个问题开始，体验你的 AI 客服工作空间。</p>
            <div class="starter-grid"><button v-for="item in starters" :key="item.title" class="starter-card" @click="useStarter(item.prompt)"><AppIcon :name="item.icon" :size="19" /><strong>{{ item.title }}</strong><span>{{ item.text }}</span><AppIcon class="starter-arrow" name="external" :size="14" /></button></div>
            <div class="welcome-foot"><AppIcon name="lock" :size="12" />{{ state.mode === 'demo' ? '当前为页面交互预览，消息仅保存在本页内存' : '消息通过认证接口发送，并保存在当前账户的服务端会话中' }}</div>
          </div>
          <div v-else class="messages">
            <div class="conversation-date"><span></span>当前会话 · {{ state.mode === 'demo' ? '前端演示' : '服务端记录' }}<span></span></div>
            <article v-for="turn in currentTurns" :key="turn.id" class="turn">
              <div class="user-message"><div class="user-bubble">{{ turn.question }}</div><span class="avatar small">{{ state.role === 'admin' ? 'A' : 'M' }}</span></div>
              <div v-if="displayAnswer(turn)" class="assistant-message"><span class="message-avatar"><AppIcon name="bot" :size="18" /></span><div class="assistant-content"><div class="message-byline">{{ state.assistantName }}<span>{{ state.mode === 'demo' ? 'AI 示例' : 'AI' }}</span><span v-if="displayAnswer(turn)?.status === 'running'" class="generating-label"><AppIcon name="loading" :size="11" class="spinning" />回复中</span></div>
                <div class="message-text">{{ displayAnswer(turn)?.text }}<span v-if="displayAnswer(turn)?.status === 'running'" class="typing-cursor"></span></div>
                <div v-if="turn.answers.at(-1)?.status === 'failed' || turn.answers.at(-1)?.status === 'cancelled'" class="message-notice"><AppIcon name="alert" :size="13" />{{ turn.answers.at(-1)?.reason }}{{ turn.activeAnswerId ? '。上方仍为上一版有效答案。' : '，此回复未完成。' }}</div>
                <div v-if="displayAnswer(turn)?.status !== 'running'" class="message-actions"><button class="icon-button" aria-label="复制回复" @click="copy(displayAnswer(turn)!)"><AppIcon name="copy" :size="14" /></button><button class="icon-button" :class="{ active: displayAnswer(turn)?.feedback === 'up' }" aria-label="有帮助" :aria-pressed="displayAnswer(turn)?.feedback === 'up'" @click="displayAnswer(turn)!.feedback = displayAnswer(turn)?.feedback === 'up' ? undefined : 'up'"><AppIcon name="like" :size="14" /></button><button class="icon-button" :class="{ active: displayAnswer(turn)?.feedback === 'down' }" aria-label="无帮助" :aria-pressed="displayAnswer(turn)?.feedback === 'down'" @click="displayAnswer(turn)!.feedback = displayAnswer(turn)?.feedback === 'down' ? undefined : 'down'"><AppIcon name="dislike" :size="14" /></button><button v-if="state.mode === 'demo' && currentTurns.at(-1)?.id === turn.id" class="text-button retry-button" :disabled="!canRetry(turn)" @click="workspace.retry(turn.id)"><AppIcon name="retry" :size="13" />重新生成<span class="attempt-count">{{ turn.answers.length }}/3</span></button><span v-if="state.mode === 'demo'" class="message-token">{{ displayAnswer(turn)?.outputTokens }} tokens · 演示估算</span></div>
              </div></div>
            </article>
          </div>
        </div>
        <div v-if="!stickToBottom && currentTurns.length" class="scroll-bottom"><button class="button small" @click="stickToBottom = true; scrollBottom()">回到最新回复<AppIcon name="down" :size="13" /></button></div>
        <div class="composer-area">
          <div v-if="!state.serviceEnabled || !activeVersion" class="composer-warning"><AppIcon name="ban" :size="14" />自动回复不可用，请联系管理员检查服务、连接、预算和助手版本。</div>
          <div class="composer-box" :class="{ 'is-busy': runningId }"><label class="sr-only" for="chat-input">输入消息</label><textarea id="chat-input" ref="composer" v-model="draft" rows="2" maxlength="2000" :disabled="!!runningId || !state.serviceEnabled || !activeVersion" placeholder="输入你的问题，开启一段对话…" @keydown="keydown"></textarea><div class="composer-toolbar"><div class="composer-tools"><span class="model-tag"><AppIcon name="sparkle" :size="13" />{{ state.mode === 'demo' ? '示例模型' : (state.connection.model || '已绑定模型') }}<AppIcon name="down" :size="10" /></span><span class="composer-text-only">仅文字</span></div><div class="send-controls"><span class="char-count" :class="{ near: draft.length > 1800 }">{{ draft.length }}/2000</span><button v-if="runningId" class="send-button stop-button" aria-label="停止生成" @click="workspace.stop()"><AppIcon name="stop" :size="17" /></button><button v-else class="send-button" aria-label="发送消息" :disabled="!draft.trim() || !state.serviceEnabled || !activeVersion" @click="send"><AppIcon name="send" :size="20" /></button></div></div></div>
          <div class="composer-footer"><span>{{ state.mode === 'demo' ? '预设示例回复 · 未连接真实 AI' : '流式回复 · 结果以服务端最终状态为准' }}</span><span class="desktop-only">Enter 发送<span class="key-divider">·</span>Shift + Enter 换行</span></div>
        </div>
      </section>
      <aside class="conversation-inspector" :class="{ 'show-mobile-info': showInfo }" aria-label="会话概览">
        <section class="card inspector-card"><div class="inspector-title"><h2>会话概览</h2><AppIcon name="sliders" :size="15" /></div><div class="inspector-assistant"><span class="tag-icon"><AppIcon name="bot" :size="23" /></span><div><strong>{{ state.assistantName }}</strong><span>内部通用问答 · {{ activeVersion?.id ?? '未启用' }}</span></div></div><p class="inspector-description">{{ state.assistantDescription }}</p><div class="divider"></div><div class="metric-line"><span>当前消息</span><strong>{{ currentTurns.length }} <small>轮对话</small></strong></div><div class="metric-line"><span>上下文范围</span><span class="badge green">仅当前会话</span></div><div class="inspector-progress"><div class="metric-line"><span>上下文估算</span><span class="tabular">{{ contextTokens.toLocaleString() }} <small>/ 4,000</small></span></div><div class="progress-track"><div class="progress-fill" :style="{ width: Math.min(100, contextTokens / 40) + '%' }"></div></div></div><div class="divider"></div><div class="metric-line"><span class="flex-row"><AppIcon name="shield" :size="14" />预算状态</span><span class="text-green">{{ state.mode === 'demo' ? '演示限制' : '服务端控制' }}</span></div><p class="inspector-tip">费用包含已确认消费与待核对预留。{{ state.role === 'admin' ? (state.mode === 'demo' ? '示例剩余额度 ' : '当前剩余额度 ') + money(availableCents) + '。' : '具体额度由管理员管理。' }}</p><RouterLink v-if="state.role === 'admin'" class="inspector-link" to="/usage">查看用量与预算<AppIcon name="arrow" :size="13" /></RouterLink></section>
        <section class="card inspector-card recent-card"><div class="inspector-title"><h2>最近的对话</h2><RouterLink class="text-button" to="/history">全部<AppIcon name="chevron" :size="11" /></RouterLink></div><button v-for="item in recent" :key="item.id" class="recent-item" @click="workspace.selectConversation(item.id)"><span class="recent-icon"><AppIcon name="chat" :size="14" /></span><span><strong>{{ item.title }}</strong><small>{{ item.updatedAt }}</small></span><AppIcon name="chevron" :size="13" /></button><p v-if="!recent.length" class="subtle">发送第一条消息后，对话将出现在这里。</p></section>
        <section v-if="state.mode === 'demo'" class="preview-scenario"><span class="flex-row"><AppIcon name="play" :size="12" />交互场景</span><label class="sr-only" for="scenario">演示场景</label><select id="scenario" v-model="state.scenario" :disabled="!!runningId"><option value="normal">正常回复</option><option value="disconnect">模拟网络中断</option><option value="budget">模拟额度不足</option></select><p>仅用于体验页面状态，不会发生真实调用。</p></section>
      </aside>
    </div>
  </div>
</template>
