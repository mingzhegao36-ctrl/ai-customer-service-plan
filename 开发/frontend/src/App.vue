<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { workspace } from './stores/workspace'
import AppIcon from './components/AppIcon.vue'
import CommandPalette from './components/CommandPalette.vue'
import { navigation } from './data/navigation'
const route = useRoute()
const router = useRouter()
const { state } = workspace
const mobileNav = ref(false)
const profileOpen = ref(false)
const searchOpen = ref(false)
const mobileViewport = ref(window.innerWidth <= 960)
const navElement = ref<HTMLElement>()
let navTrigger: HTMLElement | null = null
const navItems = computed(() => navigation.filter(n => !n.admin || state.role === 'admin'))
const navGroups = computed(() => ['工作台', '管理'].map(title => ({ title, items: navItems.value.filter(n => n.section === title) })).filter(g => g.items.length))
const pendingCount = computed(() => state.jobs.filter(job => job.status !== 'completed').length)
const isLogin = computed(() => route.path === '/login')
watch(() => route.path, () => { mobileNav.value = false; profileOpen.value = false })
watch(mobileNav, async open => {
  if (open) { navTrigger = document.activeElement as HTMLElement; await nextTick(); navElement.value?.querySelector<HTMLElement>('a,button')?.focus() }
  else { await nextTick(); if (!searchOpen.value) navTrigger?.focus() }
})
async function logout() { await workspace.logout(); await router.push('/login') }
function pageHidden() { if (state.mode === 'demo') workspace.stop('failed', '页面已离开，演示回复已停止') }
function shortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && state.role && !isLogin.value) { event.preventDefault(); mobileNav.value = false; searchOpen.value = !searchOpen.value }
  if (event.key === 'Escape') { mobileNav.value = false; profileOpen.value = false }
  if (event.key === 'Tab' && mobileNav.value) {
    const focusable = navElement.value?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled)')
    const first = focusable?.[0], last = focusable?.[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
function resize() { mobileViewport.value = window.innerWidth <= 960; if (!mobileViewport.value) mobileNav.value = false }
function dismissProfile(event: PointerEvent) { if (event.target instanceof Element && !event.target.closest('.profile-wrap')) profileOpen.value = false }
onMounted(() => { window.addEventListener('pagehide', pageHidden); window.addEventListener('keydown', shortcut); window.addEventListener('resize', resize); window.addEventListener('pointerdown', dismissProfile) })
onUnmounted(() => { window.removeEventListener('pagehide', pageHidden); window.removeEventListener('keydown', shortcut); window.removeEventListener('resize', resize); window.removeEventListener('pointerdown', dismissProfile) })
</script>
<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <div v-if="!isLogin" class="workspace-shell">
    <button v-if="mobileNav" class="nav-backdrop" aria-label="关闭导航" @click="mobileNav = false"></button>
    <aside ref="navElement" class="sidebar" :class="{ 'is-open': mobileNav }" :inert="mobileViewport && !mobileNav" aria-label="工作空间导航">
      <div class="sidebar-brand-row"><RouterLink class="brand" :to="state.role === 'admin' ? '/overview' : '/chat'"><img src="/mark.svg" alt="" /><span>知应<span class="brand-en">AI SUPPORT</span></span></RouterLink><button class="icon-button sidebar-close" aria-label="收起导航" @click="mobileNav = false"><AppIcon name="close" /></button></div>
      <div class="workspace-label"><span class="workspace-monogram">W</span><span>{{ state.workspaceName }}<small><span class="status-dot"></span>内部工作空间</small></span><AppIcon name="lock" :size="13" /></div>
      <div v-for="group in navGroups" :key="group.title" class="nav-group"><div class="nav-section-label">{{ group.title }}</div><nav class="nav-items" :aria-label="group.title"><RouterLink v-for="item in group.items" :key="item.path" :to="item.path" :aria-label="item.title" class="nav-item"><AppIcon :name="item.icon" :size="18" /><span>{{ item.title }}</span><span v-if="item.path === '/tasks' && pendingCount" class="nav-count" aria-hidden="true">{{ pendingCount }}</span><span v-if="item.path === '/overview'" class="nav-active-dot" aria-hidden="true"></span></RouterLink></nav></div>
      <div class="nav-section-label future-label">下一阶段</div>
      <RouterLink class="future-nav" to="/modules"><AppIcon name="book" /><span>知识库</span><small>V2</small></RouterLink>
      <RouterLink class="future-nav" to="/modules"><AppIcon name="headset" /><span>人工客服</span><small>V2</small></RouterLink>
      <RouterLink class="future-nav" to="/modules"><AppIcon name="flask" /><span>训练与评测</span><small>V4</small></RouterLink>
      <div class="sidebar-bottom">
        <div class="growth-card"><span class="growth-orbit" aria-hidden="true"></span><span class="tiny-icon"><AppIcon name="sparkle" :size="19" /></span><strong>服务的下一种可能</strong><p>从每一次对话出发，<br />让知识与服务相连。</p><RouterLink to="/modules">探索功能规划 <AppIcon name="arrow" :size="14" /></RouterLink></div>
        <div class="profile-wrap"><button class="profile-button" :aria-expanded="profileOpen" @click="profileOpen = !profileOpen"><span class="avatar small">{{ state.role === 'admin' ? 'A' : 'M' }}</span><span>{{ state.mode === 'demo' ? (state.role === 'admin' ? '示例管理员' : '示例内部使用者') : state.userName }}<small>{{ state.mode === 'demo' ? '前端体验身份' : (state.role === 'admin' ? '管理员' : '内部使用者') }}</small></span><AppIcon name="more" /></button>
          <div v-if="profileOpen" class="profile-menu"><RouterLink v-if="state.mode === 'demo'" to="/login"><AppIcon name="sliders" :size="16" />切换预览身份</RouterLink><button @click="logout"><AppIcon name="logout" :size="16" />{{ state.mode === 'demo' ? '退出演示' : '退出登录' }}</button></div>
        </div>
      </div>
    </aside>
    <div class="main-shell" :inert="mobileNav">
      <header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-menu" aria-label="打开导航" :aria-expanded="mobileNav" @click="mobileNav = true"><AppIcon name="menu" /></button><span class="breadcrumb-root">工作空间</span><AppIcon name="chevron" :size="14" /><span>{{ route.meta.title }}</span></div><div class="topbar-actions"><button class="global-search" aria-label="搜索页面与会话" aria-keyshortcuts="Control+K Meta+K" @click="searchOpen = true"><AppIcon name="search" :size="15" /><span>搜索工作空间</span><kbd>Ctrl K</kbd></button><span class="topbar-divider"></span><span class="preview-tag"><span class="status-dot" :class="{ gray: state.apiStatus !== 'ready' }"></span>{{ state.mode === 'demo' ? '前端预览' : (state.apiStatus === 'ready' ? '后端已连接' : '后端离线') }}</span><RouterLink class="icon-button help-link" to="/modules" aria-label="查看功能模块与预览说明"><AppIcon name="help" :size="19" /></RouterLink><span class="avatar top-avatar">{{ state.role === 'admin' ? 'A' : 'M' }}</span></div></header>
      <main id="main-content" tabindex="-1" class="main-content"><RouterView /></main>
    </div>
  </div>
  <main v-else id="main-content"><RouterView /></main>
  <CommandPalette v-if="!isLogin && state.role" :open="searchOpen" @close="searchOpen = false" />
  <Transition name="toast"><div v-if="state.toast" class="toast-message" role="status"><AppIcon name="success" :size="18" /><span>{{ state.toast }}</span><button class="icon-button" aria-label="关闭提示" @click="state.toast = ''"><AppIcon name="close" :size="15" /></button></div></Transition>
</template>
