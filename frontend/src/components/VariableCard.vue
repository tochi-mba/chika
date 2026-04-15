<template>
  <div class="var-card">
    <div class="header">
      <span class="name">{{ variable.name }}</span>
      <span class="badge" :class="variable.var_type">{{ variable.var_type }}</span>
      <span class="size">{{ fmtSize(variable.size_bytes) }}</span>
    </div>
    <div v-if="variable.value_preview" class="preview">{{ variable.value_preview }}</div>
  </div>
</template>

<script setup>
const props = defineProps({ variable: Object })

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  return (bytes / 1024).toFixed(1) + 'KB'
}
</script>

<style scoped>
.var-card {
  background: #1a1a22;
  border: 1px solid #2a2a35;
  border-radius: 8px;
  padding: 8px 10px;
  margin: 3px 0;
}
.header { display: flex; align-items: center; gap: 8px; }
.name { font-family: monospace; font-size: 13px; color: #a8a0ff; flex: 1; }
.badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
}
.badge.text     { background: #1a2a3a; color: #60a0e0; }
.badge.json     { background: #2a2a1a; color: #d0c060; }
.badge.bytes    { background: #2a1a2a; color: #c060d0; }
.badge.file_path { background: #1a2a1a; color: #60d080; }
.size { font-size: 11px; color: #555; }

.preview {
  font-family: monospace;
  font-size: 11px;
  color: #888;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
