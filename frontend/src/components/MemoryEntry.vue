<template>
  <div class="mem-entry">
    <div class="header" @click="open = !open">
      <span class="key">{{ entry.key }}</span>
      <span v-if="entry.ttl_days" class="ttl">TTL {{ entry.ttl_days }}d</span>
      <span class="toggle">{{ open ? '▲' : '▼' }}</span>
    </div>
    <div v-if="open" class="value">{{ entry.value }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
defineProps({ entry: Object })
const open = ref(false)
</script>

<style scoped>
.mem-entry {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 3px solid var(--success);
  border-radius: 10px;
  margin: 6px 12px;
  overflow: hidden;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.mem-entry:hover {
  border-color: var(--border-strong);
  border-left-color: color-mix(in srgb, var(--success) 80%, var(--accent));
}

.header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: var(--surface-2);
}
.header:hover { background: color-mix(in srgb, var(--success) 5%, var(--surface-2)); }

.key {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--success);
  font-weight: 500;
}
.ttl {
  font-size: 10px;
  color: var(--text-3);
  padding: 1px 7px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.toggle { font-size: 10px; color: var(--text-3); }

.value {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
  line-height: 1.5;
  font-family: var(--font-mono);
}
</style>
