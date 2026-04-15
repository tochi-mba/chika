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
  background: #1a1a22;
  border: 1px solid #2a2a35;
  border-radius: 8px;
  margin: 3px 0;
  overflow: hidden;
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  cursor: pointer;
  user-select: none;
}
.header:hover { background: #1e1e28; }
.key { flex: 1; font-family: monospace; font-size: 12px; color: #80d0a0; }
.ttl { font-size: 10px; color: #888; padding: 1px 5px; background: #222; border-radius: 8px; }
.toggle { font-size: 10px; color: #555; }
.value {
  padding: 6px 10px;
  font-size: 12px;
  color: #c0c0d0;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #2a2a35;
  background: #13131a;
}
</style>
