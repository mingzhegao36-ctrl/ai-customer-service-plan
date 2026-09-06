<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { workspace } from '../stores/workspace'
import AppIcon from '../components/AppIcon.vue'
import type { Role } from '../types'

const router = useRouter()
const username = ref('admin')
const password = ref('')
const remember = ref(false)

async function enter() {
  if (await workspace.login(username.value, password.value, remember.value)) {
    await router.push(workspace.state.role === 'admin' ? '/overview' : '/chat')
  }
}
async function enterDemo(role: Role) {
  workspace.setRole(role)
  await router.push(role === 'admin' ? '/overview' : '/chat')
}
</script>
<template>
  <div class="login-page">
    <a class="login-home" href="/space.html">知应 <span>AI SUPPORT</span></a>
    <div class="login-art"><span class="login-orbit"></span><span class="login-orbit second"></span><div class="login-planet"></div><p>EVERY CONVERSATION<br />IS A NEW WORLD.</p></div>
    <section class="login-panel">
      <span class="eyebrow">YOUR NEXT ORBIT</span>
      <h1>进入你的<br />客服工作空间。</h1>
      <p class="muted">{{ workspace.state.mode === 'demo' ? '选择预览身份，体验页面与功能模块。' : '使用后端账户登录。权限、会话和配置均以服务端数据为准。' }}</p>
      <template v-if="workspace.state.mode === 'demo'"><button class="identity-choice" @click="enterDemo('admin')"><span class="tag-icon"><AppIcon name="shield" :size="24" /></span><span><strong>管理员</strong><small>聊天、配置、预算与任务管理</small></span><AppIcon name="arrow" /></button><button class="identity-choice" @click="enterDemo('member')"><span class="tag-icon"><AppIcon name="chat" :size="24" /></span><span><strong>内部使用者</strong><small>个人对话与会话记录</small></span><AppIcon name="arrow" /></button></template>
      <form v-else class="login-form" @submit.prevent="enter">
        <label class="form-field"><span>用户名</span><input v-model.trim="username" class="input" autocomplete="username" maxlength="80" required /></label>
        <label class="form-field"><span>密码</span><input v-model="password" class="input" type="password" autocomplete="current-password" minlength="8" maxlength="128" required /></label>
        <label class="login-remember"><input v-model="remember" type="checkbox" />保持登录</label>
        <p v-if="workspace.state.authError" class="login-error" role="alert">{{ workspace.state.authError }}</p>
        <button class="button primary full" type="submit" :disabled="workspace.state.loading"><AppIcon :name="workspace.state.loading ? 'loading' : 'login'" :class="{ spinning: workspace.state.loading }" :size="16" />{{ workspace.state.loading ? '正在登录…' : '登录工作空间' }}</button>
      </form>
      <div class="note neutral"><AppIcon name="lock" :size="16" /><span>{{ workspace.state.mode === 'demo' ? '仅使用示例数据，不收集密码或 API Key。刷新页面会重置预览。' : '登录态使用 HttpOnly Cookie；密码不会写入浏览器存储。' }}</span></div>
      <a class="login-back" href="/space.html">← 返回星球首页</a>
    </section>
  </div>
</template>
