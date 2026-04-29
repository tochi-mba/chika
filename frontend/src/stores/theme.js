import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')

  // Use stored preference; fall back to OS setting
  const stored = localStorage.getItem('chika_theme')
  const isDark = ref(stored !== null ? stored === 'dark' : mq.matches)

  // Track OS changes only when the user has no explicit override
  mq.addEventListener('change', e => {
    if (localStorage.getItem('chika_theme') === null) {
      isDark.value = e.matches
    }
  })

  function toggle() {
    isDark.value = !isDark.value
    localStorage.setItem('chika_theme', isDark.value ? 'dark' : 'light')
  }

  // Removes override and follows OS preference again
  function useSystem() {
    localStorage.removeItem('chika_theme')
    isDark.value = mq.matches
  }

  return { isDark, toggle, useSystem }
})
