import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      include: ['src/**/*.{test,spec}.js', 'src/**/__tests__/*.{test,spec}.js'],
      setupFiles: ['./e2e/_unit-setup.js'],
    },
  }),
)
