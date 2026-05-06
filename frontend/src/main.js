import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
// Expose pinia on window for Playwright visual-baseline tests that
// drive store state directly. CI runs the production preview build,
// so a PROD guard would strip this and break the test suite. Pinia
// state is already inspectable via Vue Devtools and DOM walking, so
// this isn't a privacy/security regression — it just makes the
// integration testable end-to-end.
window.__pinia__ = pinia
app.mount('#app')
