import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import './styles.css'
import './space-theme.css'
import './workspace-ui.css'
import { workspace } from './stores/workspace'
await workspace.initialize()
createApp(App).use(router).mount('#app')
