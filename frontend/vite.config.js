import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const API_URL = process.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL  = API_URL.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // Skill UIs live under ../chika/skills/*_skill/ui/*.vue — outside
    // the frontend root by design (each skill folder is the source of
    // truth for its tools, routes, AND UI). Vite's default fs.allow
    // restricts dev-server imports to the project root, so we widen
    // it to the repo root so the SettingsModal's import.meta.glob can
    // resolve those component files at build/dev time.
    fs: {
      allow: ['..'],
    },
    proxy: {
      '/api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/ws': {
        target: WS_URL,
        ws: true,
        changeOrigin: true,
      },
      '/health': {
        target: API_URL,
        changeOrigin: true,
      },
    },
  },
  // ``vite preview`` is what Playwright runs against. By default it
  // would also pick up server.proxy and try to forward /ws to a
  // backend that isn't running during e2e — which threw cascading
  // ``ws proxy socket error: ECONNABORTED`` errors that polluted the
  // console (causing smoke "no console errors" to fail) AND clobbered
  // the Playwright init script's window.WebSocket replacement before
  // it could be observed. Preview gets an empty proxy table so the
  // mocked-in-browser WS layer has the field to itself.
  preview: {
    port: 4173,
    proxy: {},
  },
  define: {
    __API_URL__: JSON.stringify(process.env.VITE_API_URL || ''),
  },
})
