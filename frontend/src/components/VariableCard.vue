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
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  padding: 10px 12px;
  margin: 6px 12px;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.var-card:hover {
  border-color: var(--border-strong);
  border-left-color: var(--accent-2, var(--accent));
}

.header { display: flex; align-items: center; gap: 8px; }
.name {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--accent);
  font-weight: 500;
  flex: 1;
}
.badge {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 500;
  background: var(--surface-2);
  color: var(--text-2);
}
.badge.text      { color: var(--accent); background: var(--accent-dim); }
.badge.json      { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); }
.badge.bytes     { color: var(--accent-2); background: color-mix(in srgb, var(--accent-2) 14%, transparent); }
.badge.file_path { color: var(--success); background: color-mix(in srgb, var(--success) 14%, transparent); }

.size {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
}

.preview {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  margin-top: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}
</style>
