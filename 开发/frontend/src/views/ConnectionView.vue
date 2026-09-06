<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import PageHeading from '../components/PageHeading.vue'
import { workspace } from '../stores/workspace'
import type { ConnectionTestTicket } from '../types'

const { state } = workspace
const form = reactive({
  name: state.connection.name,
  baseUrl: state.connection.baseUrl,
  model: state.connection.model,
  secret: '',
  currency: state.connection.currency || 'CNY',
  inputPrice: state.connection.inputPrice ?? 0,
  outputPrice: state.connection.outputPrice ?? 0,
  maxInputTokens: state.connection.maxInputTokens || 4000,
  maxOutputTokens: state.connection.maxOutputTokens || 1200,
})
const saving = ref(false)
const testing = ref(false)
let pending: ConnectionTestTicket | undefined
let testTimer: ReturnType<typeof setTimeout> | undefined

async function save() {
  saving.value = true
  try { return await workspace.saveConnection(form) } finally { saving.value = false }
}

function runTest() {
  testing.value = true
  if (state.mode === 'demo') {
    if (!workspace.saveConnection(form)) { testing.value = false; return }
    const ticket = workspace.beginConnectionTest()
    if (!ticket) { testing.value = false; return }
    pending = ticket
    testTimer = setTimeout(() => {
      workspace.completeConnectionTest(ticket)
      pending = undefined
      testing.value = false
    }, 550)
    return
  }
  void runLiveTest()
}

async function runLiveTest() {
  try {
    if (!(await save())) return
    await workspace.testConnection()
    form.secret = ''
  } finally { testing.value = false }
}
function cancelPendingTest() {
  clearTimeout(testTimer)
  if (pending) workspace.cancelConnectionTest(pending)
  if (state.mode === 'demo' && testing.value) state.connection.tested = false
}
onBeforeRouteLeave(cancelPendingTest)
onBeforeUnmount(cancelPendingTest)
</script>
<template>
  <PageHeading title="模型连接" subtitle="连接模型的入口，也为每一次调用建立清楚的边界。" eyebrow="MODEL CONNECTION"><span class="badge orange">V1 · 单供应商</span></PageHeading>
  <div class="two-column-layout">
    <section class="card">
      <div class="card-header"><div><h2>供应商连接</h2><p>{{ state.mode === 'demo' ? '当前为示例配置，不发送真实网络请求' : 'OpenAI 兼容接口；凭据仅提交给后端保存' }}</p></div><span class="badge" :class="{ green: state.connection.tested }"><span class="status-dot"></span>{{ state.connection.tested ? (state.mode === 'demo' ? '模拟可用' : '连接可用') : (state.mode === 'demo' ? '待模拟测试' : '待真实测试') }}</span></div>
      <form class="card-body" @submit.prevent="save">
        <label class="form-field"><span>连接名称</span><input v-model="form.name" class="input" maxlength="50" required placeholder="例如：内部客服模型" /></label>
        <label class="form-field"><span>API 地址</span><input v-model="form.baseUrl" class="input code" type="url" required maxlength="250" placeholder="https://api.example.com/v1" /><small>{{ state.mode === 'demo' ? '仅用于配置交互演示。' : '后端会校验地址，并阻断不安全的内网目标。' }}</small></label>
        <label class="form-field"><span>模型标识</span><input v-model="form.model" class="input code" required maxlength="100" placeholder="support-model" /></label>
        <label class="form-field"><span>API Key <span v-if="state.connection.secretConfigured" class="inline-muted">已配置 {{ state.connection.secretHint }}</span></span><div class="disabled-secret"><AppIcon name="lock" :size="16" /><input v-model="form.secret" class="input" type="password" :required="state.mode === 'live' && !state.connection.secretConfigured" autocomplete="new-password" :placeholder="state.connection.secretConfigured ? '留空则保留现有密钥' : '输入供应商 API Key'" /></div><small>密钥不会回显，也不会写入 VITE_* 环境变量或浏览器存储。</small></label>
        <div class="form-grid-2"><label class="form-field"><span>计费币种</span><input v-model="form.currency" class="input code" minlength="3" maxlength="3" required /></label><label class="form-field"><span>最大输出 Token</span><input v-model.number="form.maxOutputTokens" class="input" type="number" min="1" max="100000" required /></label></div>
        <div class="form-grid-2"><label class="form-field"><span>输入价／百万 Token</span><input v-model.number="form.inputPrice" class="input" type="number" min="0" step="0.00000001" required /></label><label class="form-field"><span>输出价／百万 Token</span><input v-model.number="form.outputPrice" class="input" type="number" min="0" step="0.00000001" required /></label></div>
        <label class="form-field"><span>最大输入 Token</span><input v-model.number="form.maxInputTokens" class="input" type="number" min="1" max="1000000" required /></label>
        <div class="form-actions"><button type="button" class="button" :disabled="testing || saving" @click="runTest"><AppIcon :name="testing ? 'loading' : 'plug'" :size="14" :class="{ spinning: testing }" />{{ testing ? (state.mode === 'demo' ? '模拟测试中…' : '真实测试中…') : (state.mode === 'demo' ? '模拟连接测试' : '保存并真实测试') }}</button><button class="button primary" type="submit" :disabled="saving || testing"><AppIcon name="check" :size="14" />{{ state.mode === 'demo' ? '保存示例配置' : '保存连接' }}</button></div>
      </form>
    </section>
    <aside class="stack"><section class="card"><div class="card-header"><h2>当前连接概览</h2><AppIcon name="plug" :size="17" /></div><div class="card-body"><div class="connection-logo"><AppIcon name="sparkle" :size="26" /><span><strong>{{ state.connection.name || '尚未配置' }}</strong><small>{{ state.mode === 'demo' ? 'DEMO CONNECTION' : 'OPENAI COMPATIBLE' }}</small></span></div><div class="divider"></div><div class="detail-list"><div><span>模型</span><strong class="model-id">{{ state.connection.model || '—' }}</strong></div><div><span>使用助手</span><strong>{{ state.assistantName }}</strong></div><div><span>连接状态</span><strong>{{ state.connection.status || (state.connection.tested ? 'ready' : 'draft') }}</strong></div><div><span>凭据</span><strong>{{ state.connection.secretConfigured ? '已加密保存' : '未配置' }}</strong></div></div></div></section><div class="note"><AppIcon name="shield" :size="16" /><span>{{ state.mode === 'demo' ? '模拟测试只改变页面状态。' : '连接测试由后端任务执行。请同时运行 Worker，并以任务中心的最终状态为准。' }}</span></div></aside>
  </div>
</template>
