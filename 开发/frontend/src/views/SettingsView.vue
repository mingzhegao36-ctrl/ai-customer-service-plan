<script setup lang="ts">
import { ref } from 'vue'
import PageHeading from '../components/PageHeading.vue'
import AppIcon from '../components/AppIcon.vue'
import AppModal from '../components/AppModal.vue'
import { workspace } from '../stores/workspace'

const { state } = workspace
const name = ref(state.workspaceName)
const confirmPause = ref(false)
async function save() { if (name.value.trim()) await workspace.saveWorkspace(name.value) }
async function resume() { await workspace.setService(true) }
async function pause() { await workspace.setService(false); confirmPause.value = false }
</script>
<template>
  <PageHeading title="工作空间设置" :subtitle="state.mode === 'demo' ? '管理当前工作空间与演示服务状态。' : '管理当前工作空间与服务端自动回复状态。'" eyebrow="WORKSPACE SETTINGS" />
  <div class="two-column-layout"><div class="stack">
    <section class="card"><div class="card-header"><h2>基本信息</h2><span class="badge">内部工作空间</span></div><form class="card-body" @submit.prevent="save"><label class="form-field"><span>工作空间名称</span><input v-model="name" class="input" maxlength="30" required /></label><div class="form-actions"><button class="button primary" type="submit">保存名称</button></div></form></section>
    <section class="card"><div class="card-header"><h2>自动回复</h2><span class="badge" :class="state.serviceEnabled ? 'green' : 'orange'">{{ state.serviceEnabled ? (state.mode === 'demo' ? '演示已开启' : '服务已开启') : (state.mode === 'demo' ? '演示已暂停' : '服务已暂停') }}</span></div><div class="card-body"><p class="muted">暂停后，当前运行会被撤销，新消息会由后端统一拦截；待核对预算仍保留。</p><div class="form-actions"><button v-if="state.serviceEnabled" class="button danger" @click="confirmPause = true"><AppIcon name="ban" :size="14" />{{ state.mode === 'demo' ? '暂停演示自动回复' : '暂停自动回复' }}</button><button v-else class="button primary" @click="resume">{{ state.mode === 'demo' ? '恢复演示自动回复' : '恢复自动回复' }}</button></div></div></section>
  </div><div class="stack"><section class="card"><div class="card-header"><h2>当前环境</h2><AppIcon name="layers" /></div><div class="card-body"><dl class="detail-list"><div><dt>版本</dt><dd>{{ state.mode === 'demo' ? 'v0.3 · 冻结演示' : 'v0.4 · 前后端联调' }}</dd></div><div><dt>数据</dt><dd>{{ state.mode === 'demo' ? '浏览器页面内存' : '后端数据库' }}</dd></div><div><dt>API</dt><dd>{{ state.mode === 'demo' ? '未接入' : (state.apiStatus === 'ready' ? '已连接' : '离线') }}</dd></div><div><dt>访客客服</dt><dd>V2 待开发</dd></div><div><dt>知识库</dt><dd>V2 待开发</dd></div></dl></div></section><div class="note"><AppIcon name="lock" :size="16" /><span>{{ state.mode === 'demo' ? '演示数据刷新后重置。' : '认证、权限、配置修订和服务开关均由后端校验。供应商密钥只在连接页提交给后端。' }}</span></div><a class="button" href="/space.html"><AppIcon name="external" :size="14" />返回星球首页</a></div></div>
  <AppModal :open="confirmPause" title="暂停自动回复？" description="后端会递增授权纪元并取消当前运行。已有会话与待核对预留仍会保留。" @close="confirmPause = false"><div class="form-actions"><button class="button" @click="confirmPause = false">取消</button><button class="button danger" @click="pause">确认暂停</button></div></AppModal>
</template>
