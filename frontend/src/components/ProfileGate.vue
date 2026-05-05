<template>
  <div class="profile-gate" v-if="!unlocked">
    <div class="gate-card">
      <div class="gate-brand">
        <div class="gate-mark" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
          </svg>
        </div>
        <span>Chika</span>
      </div>

      <h2 class="gate-title">Who's working today?</h2>
      <p class="gate-sub">Pick a profile to load its memory + workspace.</p>

      <div v-if="loading" class="gate-loading">Loading profiles…</div>
      <div v-else-if="error" class="gate-error">{{ error }}</div>

      <ul v-else-if="!chosen" class="gate-list">
        <li v-for="p in profiles" :key="p.name">
          <button class="gate-pick" @click="pickProfile(p)">
            <span class="gate-name">{{ p.name }}</span>
            <span class="gate-badge" v-if="p.has_password" title="Password required">🔒</span>
            <span class="gate-arrow">→</span>
          </button>
        </li>
        <li>
          <button class="gate-pick gate-create" @click="showCreate = true">
            <span class="gate-name">+ New profile</span>
          </button>
        </li>
      </ul>

      <form v-else-if="chosen.has_password" class="gate-pwd" @submit.prevent="submitPassword">
        <button class="gate-back" type="button" @click="resetChoice">← Back</button>
        <label>
          <span>Password for {{ chosen.name }}</span>
          <input
            type="password"
            ref="pwdInput"
            v-model="password"
            autocomplete="current-password"
            :disabled="submitting"
            placeholder="••••••"
          />
        </label>
        <div v-if="pwdError" class="gate-error">{{ pwdError }}</div>
        <button class="gate-go" type="submit" :disabled="submitting || !password">
          {{ submitting ? 'Unlocking…' : 'Continue' }}
        </button>
        <!-- Always-available escape hatch: if you can't get in, make a new
             profile rather than getting locked out. -->
        <button
          v-if="pwdError"
          class="gate-back gate-fallback"
          type="button"
          @click="resetChoice(); showCreate = true"
        >
          Locked out? Create a new profile instead →
        </button>
      </form>

      <div v-if="showCreate" class="gate-create-form">
        <button class="gate-back" type="button" @click="showCreate = false">← Back</button>
        <label>
          <span>Profile name</span>
          <input v-model="newName" :disabled="submitting" placeholder="e.g. tochi" />
        </label>
        <label>
          <span>Password (optional)</span>
          <input
            v-model="newPwd"
            type="password"
            :disabled="submitting"
            autocomplete="new-password"
            placeholder="leave empty for no password"
          />
        </label>
        <div v-if="createError" class="gate-error">{{ createError }}</div>
        <button class="gate-go" type="button" :disabled="submitting || !newName.trim()" @click="submitCreate">
          {{ submitting ? 'Creating…' : 'Create + use' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'

const props = defineProps({
  apiKey:   { type: String, default: '' },
  sessionId:{ type: String, default: '' },
})
const emit = defineEmits(['unlocked'])

const profiles    = ref([])
const loading     = ref(true)
const error       = ref('')
const chosen      = ref(null)
const password    = ref('')
const pwdError    = ref('')
const pwdInput    = ref(null)
const submitting  = ref(false)
const unlocked    = ref(false)

const showCreate  = ref(false)
const newName     = ref('')
const newPwd      = ref('')
const createError = ref('')

function authHeaders() {
  const h = { 'Content-Type': 'application/json' }
  if (props.apiKey) h['Authorization'] = `Bearer ${props.apiKey}`
  return h
}

async function loadProfiles() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/profiles', { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    profiles.value = data.profiles || []
  } catch (err) {
    error.value = `Couldn't load profiles: ${err.message}`
  } finally {
    loading.value = false
  }
}

function pickProfile(p) {
  chosen.value = p
  password.value = ''
  pwdError.value = ''
  if (!p.has_password) {
    submitSelect('')
  } else {
    nextTick(() => pwdInput.value?.focus())
  }
}

function resetChoice() {
  chosen.value = null
  password.value = ''
  pwdError.value = ''
}

async function submitPassword() {
  await submitSelect(password.value)
}

async function submitSelect(pwd) {
  if (!chosen.value) return
  submitting.value = true
  pwdError.value = ''
  try {
    const res = await fetch('/api/profiles/select', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        session_id: props.sessionId || 'frontend',
        name:       chosen.value.name,
        password:   pwd,
      }),
    })
    if (res.status === 401) {
      pwdError.value = 'Wrong password.'
      return
    }
    if (!res.ok) {
      pwdError.value = `Failed (${res.status})`
      return
    }
    const data = await res.json()
    unlocked.value = true
    emit('unlocked', data)
  } catch (err) {
    pwdError.value = `Network error: ${err.message}`
  } finally {
    submitting.value = false
  }
}

async function submitCreate() {
  createError.value = ''
  submitting.value = true
  try {
    const res = await fetch('/api/profiles/create', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        name:     newName.value.trim(),
        password: newPwd.value || null,
      }),
    })
    if (!res.ok) {
      createError.value = `Failed (${res.status})`
      return
    }
    const data = await res.json()
    showCreate.value = false
    chosen.value = { name: data.name, has_password: data.has_password }
    if (data.has_password) {
      password.value = newPwd.value
      await submitSelect(newPwd.value)
    } else {
      await submitSelect('')
    }
  } catch (err) {
    createError.value = `Network error: ${err.message}`
  } finally {
    submitting.value = false
  }
}

onMounted(loadProfiles)
</script>

<style scoped>
.profile-gate {
  position: fixed;
  inset: 0;
  background: var(--bg);
  display: grid;
  place-items: center;
  z-index: 9999;
  padding: 24px;
}
.gate-card {
  width: min(420px, 100%);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.18);
}
:root.dark .gate-card {
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.gate-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
  color: var(--text-1);
  margin-bottom: 24px;
  letter-spacing: -0.015em;
}
.gate-mark {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--accent-dim);
  color: var(--accent);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.gate-title {
  font-size: 22px;
  margin: 0 0 6px;
  color: var(--text-1);
  font-weight: 600;
  letter-spacing: -0.02em;
}
.gate-sub {
  margin: 0 0 24px;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.5;
}

.gate-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.gate-pick {
  width: 100%;
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 13px 14px;
  color: var(--text-1);
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 140ms var(--spring),
              background-color 140ms var(--spring),
              transform 140ms var(--spring);
  text-align: left;
}
.gate-pick:hover {
  border-color: var(--accent);
  background: var(--accent-dim);
  transform: translateY(-1px);
}
.gate-name { color: var(--text-1); }
.gate-badge { font-size: 12px; opacity: 0.7; }
.gate-arrow {
  color: var(--text-3);
  transition: color 140ms, transform 140ms var(--spring);
}
.gate-pick:hover .gate-arrow { color: var(--accent); transform: translateX(2px); }
.gate-create {
  color: var(--text-3);
  border-style: dashed;
  background: transparent;
}
.gate-create:hover { color: var(--accent); }

.gate-pwd, .gate-create-form {
  display: grid;
  gap: 14px;
  margin-top: 4px;
}
.gate-pwd label, .gate-create-form label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-weight: 500;
}
.gate-pwd input, .gate-create-form input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  color: var(--text-1);
  font-family: inherit;
  text-transform: none;
  letter-spacing: 0;
  transition: border-color 140ms var(--spring);
}
.gate-pwd input:focus, .gate-create-form input:focus {
  outline: none;
  border-color: var(--accent);
}
.gate-go {
  background: var(--accent);
  color: #fff;
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 10px 14px;
  font: inherit;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: background 140ms var(--spring), border-color 140ms var(--spring);
}
.gate-go:hover:not(:disabled) {
  background: var(--accent-2);
  border-color: var(--accent-2);
}
.gate-go:disabled { opacity: 0.5; cursor: not-allowed; }
.gate-back {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 0;
  font: inherit;
  font-size: 13px;
  text-align: left;
  width: max-content;
  transition: color 120ms;
}
.gate-back:hover { color: var(--text-1); }
.gate-fallback { color: var(--accent); }
.gate-fallback:hover { color: var(--accent-2); }

.gate-error {
  color: var(--error);
  font-size: 13px;
}
.gate-loading {
  color: var(--text-3);
  font-size: 14px;
}
</style>
