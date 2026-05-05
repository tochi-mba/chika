import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
// Expose pinia on window in dev/preview so Playwright tests can drive
// store state directly for visual baselines. Stripped from production
// builds via the import.meta.env.PROD check (set by Vite).
if (!import.meta.env.PROD) {
  window.__pinia__ = pinia
}
app.mount('#app')
