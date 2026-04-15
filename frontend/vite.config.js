import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const API_URL = process.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL  = API_URL.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
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
  define: {
    __API_URL__: JSON.stringify(process.env.VITE_API_URL || ''),
  },
})
