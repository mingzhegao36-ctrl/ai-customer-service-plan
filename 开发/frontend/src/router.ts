import { createRouter, createWebHashHistory } from 'vue-router'
import { workspace } from './stores/workspace'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: () => workspace.state.role === 'admin' ? '/overview' : '/chat' },
    { path: '/overview', component: () => import('./views/OverviewView.vue'), meta: { title: '工作空间概览', admin: true } },
    { path: '/login', component: () => import('./views/LoginView.vue'), meta: { title: '登录工作空间' } },
    { path: '/chat', component: () => import('./views/ChatView.vue'), meta: { title: '对话工作台' } },
    { path: '/history', component: () => import('./views/HistoryView.vue'), meta: { title: '会话记录' } },
    { path: '/assistant', component: () => import('./views/AssistantView.vue'), meta: { title: '助手配置', admin: true } },
    { path: '/connections', component: () => import('./views/ConnectionView.vue'), meta: { title: '模型连接', admin: true } },
    { path: '/usage', component: () => import('./views/UsageView.vue'), meta: { title: '用量与预算', admin: true } },
    { path: '/tasks', component: () => import('./views/TasksView.vue'), meta: { title: '任务中心', admin: true } },
    { path: '/settings', component: () => import('./views/SettingsView.vue'), meta: { title: '工作空间设置', admin: true } },
    { path: '/modules', component: () => import('./views/ModulesView.vue'), meta: { title: '功能规划' } },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})
router.beforeEach(to => {
  if (to.path !== '/login' && !workspace.state.role) return '/login'
  if (to.meta.admin && workspace.state.role !== 'admin') return '/chat'
})
router.afterEach(to => { document.title = '知应 · ' + String(to.meta.title ?? 'AI 客服工作空间') })
