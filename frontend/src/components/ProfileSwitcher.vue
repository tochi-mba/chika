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
  gap: 6px;
  background: none;
  border: 1px solid transparent;
  border-radius: 20px;
  padding: 3px 8px 3px 3px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.trigger:hover { background: #1e1e28; border-color: #2a2a35; }

.avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #6c63ff;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.name {
  font-size: 13px;
  font-weight: 600;
  color: #c8c0ff;
  text-transform: capitalize;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chevron {
  font-size: 10px;
  color: #555;
  transition: transform 0.15s;
}
.chevron.open { transform: rotate(180deg); }

/* Dropdown */
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 1999;
}

.dropdown {
  background: #1a1a24;
  border: 1px solid #2a2a35;
  border-radius: 12px;
  padding: 6px;
  min-width: 200px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  animation: pop 0.12s ease-out;
}
@keyframes pop {
  from { transform: translateY(-4px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}

.dropdown-header {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #444;
  padding: 4px 8px 6px;
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
  transition: background 0.12s;
}
.profile-item:hover { background: #242432; }
.profile-item.active { background: #1e1e2e; }

.item-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #2a2a3d;
  color: #a89fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.profile-item.active .item-avatar { background: #6c63ff; color: #fff; }

.item-name {
  flex: 1;
  font-size: 13px;
  color: #c8c8d8;
  text-transform: capitalize;
}
.profile-item.active .item-name { color: #e8e8f0; font-weight: 600; }

.active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6c63ff;
  flex-shrink: 0;
}

.divider {
  height: 1px;
  background: #2a2a35;
  margin: 6px 4px;
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
  border-radius: 8px;
  transition: background 0.12s, color 0.12s;
}
.new-btn:hover { background: #242432; color: #aaa; }
.plus { font-size: 16px; color: #555; line-height: 1; }

.new-input-row {
  display: flex;
  gap: 6px;
  padding: 4px 6px;
}
.new-input {
  flex: 1;
  background: #111118;
  border: 1px solid #2a2a35;
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
  color: #e8e8f0;
  outline: none;
}
.new-input:focus { border-color: #6c63ff; }
.go-btn {
  background: #6c63ff;
  border: none;
  border-radius: 6px;
  color: #fff;
  padding: 5px 10px;
  cursor: pointer;
  font-size: 13px;
}
.go-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
