<template>
  <div class="profile-switcher" ref="root">
    <!-- Trigger -->
    <button class="trigger" @click="toggle" :title="system.profile.name">
      <span class="avatar">{{ initial }}</span>
      <span class="name">{{ system.profile.name }}</span>
      <span class="chevron" :class="{ open }">▾</span>
    </button>

    <!-- Dropdown -->
    <Teleport to="body">
      <div
        v-if="open"
        class="dropdown"
        :style="dropdownStyle"
      >
        <div class="dropdown-header">Profiles</div>

        <button
          v-for="p in profiles"
          :key="p"
          class="profile-item"
          :class="{ active: p === system.profile.name }"
          @click="select(p)"
        >
          <span class="item-avatar">{{ p.charAt(0).toUpperCase() }}</span>
          <span class="item-name">{{ p }}</span>
          <span v-if="p === system.profile.name" class="active-dot" />
        </button>

        <div class="divider" />

        <!-- New profile -->
        <div v-if="!creating" class="new-btn" @click="creating = true">
          <span class="plus">+</span> New profile
        </div>
        <div v-else class="new-input-row">
          <input
            ref="nameInput"
            v-model="newName"
            placeholder="profile name"
            @keydown.enter="createProfile"
            @keydown.escape="creating = false"
            class="new-input"
          />
          <button class="go-btn" @click="createProfile" :disabled="!newName.trim()">→</button>
        </div>
      </div>

      <!-- Click-outside backdrop -->
      <div v-if="open" class="backdrop" @click="close" />
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useSystemStore } from '../stores/system'

const emit = defineEmits(['switch'])

const system = useSystemStore()
const open = ref(false)
const creating = ref(false)
const newName = ref('')
const nameInput = ref(null)
const root = ref(null)
const profiles = ref([])
const dropdownStyle = ref({})

const initial = computed(() =>
  (system.profile.name || 'D').charAt(0).toUpperCase()
)

async function fetchProfiles() {
  try {
    const r = await fetch('/api/profiles')
    if (r.ok) {
      const data = await r.json()
      profiles.value = data.profiles || []
    }
  } catch {}
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    fetchProfiles()
    nextTick(positionDropdown)
  }
}

function close() {
  open.value = false
  creating.value = false
  newName.value = ''
}

function positionDropdown() {
  const el = root.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  dropdownStyle.value = {
    position: 'fixed',
    top: rect.bottom + 6 + 'px',
    left: rect.left + 'px',
    zIndex: 2000,
  }
}

function select(name) {
  if (name === system.profile.name) { close(); return }
  emit('switch', name)
  close()
}

function createProfile() {
  const name = newName.value.trim().toLowerCase().replace(/\s+/g, '_')
  if (!name) return
  emit('switch', name)
  newName.value = ''
  creating.value = false
  close()
}

watch(creating, (v) => {
  if (v) nextTick(() => nameInput.value?.focus())
})

onMounted(fetchProfiles)
</script>

<style scoped>
.profile-switcher { position: relative; }

.trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px 4px 4px;
  cursor: pointer;
  font: inherit;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.trigger:hover {
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-2));
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  transform: translateY(-1px);
}

.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent), var(--accent-2, var(--accent)));
  color: #fff;
  font-size: 11.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  letter-spacing: -0.02em;
  box-shadow: 0 2px 6px color-mix(in srgb, var(--accent) 28%, transparent);
}
.name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-1);
  text-transform: capitalize;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: -0.01em;
}
.chevron {
  font-size: 10px;
  color: var(--text-3);
  transition: transform 150ms var(--spring);
}
.chevron.open { transform: rotate(180deg); }

/* Dropdown */
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 1999;
}

.dropdown {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 6px;
  min-width: 220px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18),
              0 0 0 1px color-mix(in srgb, var(--accent) 6%, transparent);
  backdrop-filter: blur(8px);
  animation: pop 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
:root.dark .dropdown {
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
}

@keyframes pop {
  from { transform: translateY(-4px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}

.dropdown-header {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 600;
  color: var(--text-3);
  padding: 6px 8px 8px;
}

.profile-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  background: none;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: background 120ms;
}
.profile-item:hover { background: var(--surface-2); }
.profile-item.active { background: var(--accent-dim); }

.item-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  letter-spacing: -0.02em;
}
.profile-item.active .item-avatar { background: var(--accent); color: #fff; }

.item-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-2);
  text-transform: capitalize;
}
.profile-item.active .item-name { color: var(--accent); font-weight: 600; }

.active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}

.divider {
  height: 1px;
  background: var(--border);
  margin: 6px 4px;
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  font-size: 13px;
  color: var(--text-3);
  cursor: pointer;
  border-radius: 8px;
  transition: background 120ms, color 120ms;
}
.new-btn:hover { background: var(--surface-2); color: var(--text-1); }
.plus { font-size: 16px; color: var(--text-3); line-height: 1; }

.new-input-row {
  display: flex;
  gap: 6px;
  padding: 4px 6px;
}
.new-input {
  flex: 1;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font: inherit;
  font-size: 12px;
  color: var(--text-1);
  outline: none;
  transition: border-color 140ms;
}
.new-input:focus { border-color: var(--accent); }
.go-btn {
  background: var(--accent);
  border: none;
  border-radius: 6px;
  color: #fff;
  padding: 5px 10px;
  cursor: pointer;
  font-size: 13px;
  transition: background 140ms;
}
.go-btn:hover:not(:disabled) { background: var(--accent-2); }
.go-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
