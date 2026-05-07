<template>
  <div class="card" :class="{ connected: state.authorized }">
    <div class="card-head">
      <div class="logo" aria-hidden="true">
        <!-- Spotify wordmark in the brand green; matches the
             official guidelines (no border, accent-on-dark surface). -->
        <svg viewBox="0 0 32 32" width="28" height="28">
          <circle cx="16" cy="16" r="16" fill="#1DB954"/>
          <path
            d="M22.7 22.4c-.3.5-.9.7-1.4.4-3.8-2.3-8.6-2.8-14.2-1.5-.5.1-1-.2-1.2-.7-.1-.5.2-1 .7-1.2 6.1-1.4 11.4-.8 15.7 1.7.5.3.7.9.4 1.3zm1.8-3.6c-.4.6-1.1.8-1.7.4-4.4-2.7-11-3.5-16.2-1.9-.7.2-1.4-.2-1.6-.8-.2-.7.2-1.4.8-1.6 5.9-1.8 13.2-.9 18.2 2.2.6.4.8 1.1.5 1.7zm.1-3.7C19 12.1 10.6 11.7 5.6 13.2c-.8.2-1.6-.2-1.9-1-.2-.8.2-1.6 1-1.9 5.7-1.7 15-1.3 21 2.3.7.4.9 1.3.5 2-.4.7-1.3.9-2 .5z"
            fill="#000"/>
        </svg>
      </div>
      <div class="meta">
        <h3>Spotify</h3>
        <p v-if="state.authorized && state.display_name">
          Connected as <strong>{{ state.display_name }}</strong>
          <span class="tier" :class="state.product">
            {{ state.product || 'unknown' }}
          </span>
        </p>
        <p v-else-if="state.authorized">Connected</p>
        <p v-else-if="!state.client_id_set" class="warn">
          Not configured — see setup instructions below.
        </p>
        <p v-else>Not connected</p>
      </div>
      <span v-if="state.authorized" class="dot ok" title="Connected" />
      <span v-else-if="!state.client_id_set" class="dot err" title="Not configured" />
      <span v-else class="dot off" title="Not connected" />
    </div>

    <div class="card-body">
      <p v-if="state.authorized" class="hint">
        Chika can play music, queue tracks, and read your library.
        <span v-if="state.shared">Connection is <strong>shared across all profiles</strong>.</span>
        <span v-else>This connection is for the <strong>{{ state.profile }}</strong> profile only.</span>
      </p>
      <p v-else-if="!state.client_id_set" class="hint">
        Chika needs a free Spotify "client ID" to connect — it takes about
        90 seconds.
      </p>
      <ol v-if="!state.client_id_set && showClientIdGuide" class="client-id-steps">
        <li>
          Open the
          <a href="https://developer.spotify.com/dashboard"
             target="_blank" rel="noopener noreferrer">Spotify Developer Dashboard</a>
          and sign in.
        </li>
        <li>Click <strong>Create app</strong>. Any name + description works.</li>
        <li>
          For <strong>Redirect URIs</strong>, paste BOTH of these and click Add:
          <pre class="code">{{ redirectUris.join('\n') }}</pre>
        </li>
        <li>
          Tick <strong>Web API</strong>, accept terms, click <strong>Save</strong>.
        </li>
        <li>
          On the new app's page, click <strong>Settings</strong> → copy the
          <strong>Client ID</strong> (a long hex string).
        </li>
        <li>Paste it below and Chika takes care of the rest.</li>
      </ol>
      <p v-else class="hint">
        Connect Spotify so Chika can play music, queue tracks, search your
        library, and control playback.
      </p>

      <!-- Inline CLIENT_ID paste field — shown until one is configured.
           No file editing, no env-var hunting, no restart. -->
      <div v-if="!state.client_id_set" class="client-id-form">
        <label for="spotify-client-id" class="client-id-label">
          Client ID
          <button
            class="client-id-toggle"
            type="button"
            @click="showClientIdGuide = !showClientIdGuide"
          >{{ showClientIdGuide ? 'hide setup steps' : 'show setup steps' }}</button>
        </label>
        <div class="client-id-row">
          <input
            id="spotify-client-id"
            v-model="clientIdDraft"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="32-character hex string from Spotify Dashboard"
            @keydown.enter.prevent="saveClientId"
          />
          <button
            class="btn-primary"
            :disabled="savingClientId || !clientIdDraft.trim()"
            @click="saveClientId"
          >{{ savingClientId ? 'Saving…' : 'Save & connect' }}</button>
        </div>
      </div>

      <div class="actions">
        <button
          v-if="!state.authorized && state.client_id_set"
          class="btn-primary"
          :disabled="connecting"
          @click="connect"
        >
          <span v-if="connecting">Opening Spotify…</span>
          <span v-else>Connect Spotify</span>
        </button>
        <button
          v-if="state.authorized"
          class="btn-ghost"
          @click="disconnect"
          :disabled="working"
        >
          {{ working ? 'Disconnecting…' : 'Disconnect' }}
        </button>
        <button
          v-if="state.authorized"
          class="btn-ghost"
          @click="connect"
          :disabled="connecting"
          title="Re-authorize (e.g. after changing your password)"
        >
          Reconnect
        </button>
      </div>

      <!-- Headless / SSH fallback: paste the URL when the browser
           didn't open. -->
      <div v-if="lastUrl && !lastOpened" class="fallback">
        <p class="fallback-label">Browser didn't open. Paste this URL into one:</p>
        <div class="fallback-row">
          <input :value="lastUrl" readonly @click="$event.target.select()"/>
          <button class="btn-ghost small" @click="copyUrl">{{ copied ? 'Copied' : 'Copy' }}</button>
        </div>
      </div>
    </div>

    <!-- Share-across-profiles toggle. Defaults off — per-profile is
         more private and matches user expectations. -->
    <div class="share-row">
      <div>
        <strong>Share connection across all profiles</strong>
        <p class="hint">
          When on, every profile uses the same Spotify account.
          When off (default), each profile connects independently.
        </p>
      </div>
      <label class="switch">
        <input
          type="checkbox"
          :checked="state.shared_setting"
          :disabled="sharing"
          @change="toggleShare($event.target.checked)"
        />
        <span class="track"><span class="thumb"/></span>
      </label>
    </div>

    <!-- Per-profile override — only shown when global sharing is on.
         Lets a single profile opt out and use its own Spotify account
         while everyone else uses the shared one. -->
    <div v-if="state.shared_setting" class="share-row">
      <div>
        <strong>Use my own Spotify for this profile</strong>
        <p class="hint">
          Overrides the shared connection just for the
          <strong>{{ state.active_profile || state.profile }}</strong>
          profile. Other profiles keep using the shared account.
        </p>
      </div>
      <label class="switch">
        <input
          type="checkbox"
          :checked="state.overrides_share"
          :disabled="overriding"
          @change="toggleOverride($event.target.checked)"
        />
        <span class="track"><span class="thumb"/></span>
      </label>
    </div>

    <p v-if="error" class="error-msg">{{ error }}</p>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, reactive } from 'vue'

const props = defineProps({
  apiKey: { type: String, default: '' },
})
const emit = defineEmits(['patch-settings'])

const state = reactive({
  authorized:        false,
  client_id_set:     false,
  display_name:      '',
  product:           '',
  profile:           '',
  active_profile:    '',
  shared:            false,
  shared_setting:    false,
  overrides_share:   false,
  // Full {profile: true} map so toggleOverride can mutate just one
  // key instead of clobbering siblings.
  profile_overrides: {},
})
const connecting = ref(false)
const working    = ref(false)
const sharing    = ref(false)
const overriding = ref(false)
const lastUrl    = ref('')
const lastOpened = ref(true)
const copied     = ref(false)
const error      = ref('')

// Client-ID setup state
const clientIdDraft     = ref('')
const savingClientId    = ref(false)
const showClientIdGuide = ref(true)
// The two redirect URIs the user must paste into their Spotify app.
// Listed verbatim so they can copy-paste both with one selection.
const redirectUris = [
  'http://127.0.0.1:8000/auth/spotify/callback',
  'http://localhost:8000/auth/spotify/callback',
]

function authHeaders() {
  const h = { 'Content-Type': 'application/json' }
  const k = props.apiKey || localStorage.getItem('chika_api_key') || ''
  if (k) h['Authorization'] = `Bearer ${k}`
  return h
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/spotify/status', { headers: authHeaders() })
    if (!res.ok) return
    const data = await res.json()
    Object.assign(state, data)
  } catch (e) {
    // Silent — status polls are best-effort.
  }
}

async function connect() {
  if (connecting.value) return
  connecting.value = true
  error.value = ''
  try {
    const res = await fetch('/api/spotify/connect', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ open_browser: true }),
    })
    const data = await res.json()
    if (data.error) {
      error.value = data.message || data.error
    } else {
      lastUrl.value = data.auth_url || ''
      lastOpened.value = !!data.opened
    }
  } catch (e) {
    error.value = String(e?.message || e)
  } finally {
    connecting.value = false
  }
}


async function saveClientId() {
  // Quick sanity check — Spotify client IDs are 32-char hex strings.
  // We don't reject other shapes (Spotify could change the format),
  // but we trim whitespace and warn on obviously-wrong inputs.
  const raw = clientIdDraft.value.trim()
  if (!raw) return
  if (raw.length < 8) {
    error.value = "That doesn't look like a Client ID — it should be ~32 chars."
    return
  }
  savingClientId.value = true
  error.value = ''
  try {
    // Write to .env via the existing PATCH endpoint. Hot-reload kicks
    // in automatically — the server's env router calls reload_clients()
    // for any CHIKA_SPOTIFY_CLIENT_ID / API_KEY change... actually wait,
    // CHIKA_SPOTIFY_CLIENT_ID isn't in the hot-reloadable env-key set.
    // It IS picked up by the spotify_oauth module on every call though,
    // so we don't need to reload the LLM client; we just need to
    // re-fetch /api/spotify/status which reads CLIENT_ID from env at
    // call time.
    const res = await fetch('/api/env', {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({
        set: { CHIKA_SPOTIFY_CLIENT_ID: raw },
      }),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `HTTP ${res.status}`)
    }
    clientIdDraft.value = ''
    // Pull fresh status — the inline form should disappear and the
    // Connect Spotify button should light up.
    await fetchStatus()
    // If status now reports client_id_set:true, immediately kick off
    // the Connect flow so the user gets the full one-click experience.
    if (state.client_id_set) {
      await connect()
    }
  } catch (e) {
    error.value = `Couldn't save Client ID: ${e?.message || e}`
  } finally {
    savingClientId.value = false
  }
}

async function disconnect() {
  if (working.value) return
  working.value = true
  try {
    await fetch('/api/spotify/disconnect', {
      method: 'POST',
      headers: authHeaders(),
    })
    state.authorized = false
    state.display_name = ''
    state.product = ''
  } finally {
    working.value = false
  }
}

async function toggleShare(checked) {
  if (sharing.value) return
  sharing.value = true
  try {
    emit('patch-settings', {
      spotify_share_across_profiles: checked ? 'on' : 'off',
    })
    state.shared_setting = checked
    // Bucket changed — re-pull status so the UI reflects the
    // new bucket's connection state (the shared bucket may not
    // have any tokens yet on first toggle-on).
    await fetchStatus()
  } finally {
    sharing.value = false
  }
}


async function toggleOverride(checked) {
  if (overriding.value) return
  overriding.value = true
  try {
    // Read existing overrides from the live status payload so we
    // don't clobber other profiles' flags — we only mutate the
    // active profile's key. The settings store drops False entries
    // when persisting, so passing False is equivalent to "unset."
    const next = { ...(state.profile_overrides || {}) }
    const profileKey = state.active_profile || state.profile || 'default'
    if (checked) next[profileKey] = true
    else delete next[profileKey]
    emit('patch-settings', { spotify_profile_overrides: next })
    state.overrides_share = checked
    state.profile_overrides = next
    await fetchStatus()
  } finally {
    overriding.value = false
  }
}

async function copyUrl() {
  try {
    await navigator.clipboard.writeText(lastUrl.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1800)
  } catch (e) {
    /* clipboard may be unavailable on insecure contexts; user can
       still select the input manually. */
  }
}

// Live update via WS — useChika.js dispatches a CustomEvent on the
// window when ``spotify_auth_changed`` arrives, so we don't have to
// poll. The polling fallback below catches the case where the WS
// channel was disconnected during the OAuth dance.
function onAuthChanged() {
  fetchStatus()
}

let pollTimer = null

onMounted(() => {
  fetchStatus()
  window.addEventListener('chika:spotify_auth_changed', onAuthChanged)
  // Belt-and-braces: poll every 4s while the modal is open. Stops
  // when the component unmounts.
  pollTimer = setInterval(fetchStatus, 4000)
})

onUnmounted(() => {
  window.removeEventListener('chika:spotify_auth_changed', onAuthChanged)
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.card.connected { border-color: color-mix(in srgb, #1DB954 36%, var(--border)); }

.card-head {
  display: flex; align-items: center; gap: 14px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border);
}
.logo { flex-shrink: 0; }
.meta { flex: 1; min-width: 0; }
.meta h3 {
  margin: 0; font-size: 15px; font-weight: 600;
  letter-spacing: -0.015em; color: var(--text-1);
}
.meta p {
  margin: 4px 0 0; font-size: 12.5px; color: var(--text-2);
  letter-spacing: -0.005em;
}
.meta p.warn { color: var(--warn); }
.meta strong { color: var(--text-1); font-weight: 600; }

.tier {
  display: inline-block; margin-left: 6px;
  padding: 1px 8px; border-radius: 999px;
  font-size: 10px; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
  background: var(--surface-2); color: var(--text-3);
}
.tier.premium { background: color-mix(in srgb, #1DB954 14%, transparent); color: #1DB954; }

.dot {
  flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%;
}
.dot.ok  { background: #1DB954; box-shadow: 0 0 0 4px color-mix(in srgb, #1DB954 18%, transparent); }
.dot.err { background: var(--error); }
.dot.off { background: var(--text-3); }

.card-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }
.hint {
  margin: 0; font-size: 12.5px; color: var(--text-2);
  line-height: 1.55; letter-spacing: -0.005em;
}
.hint code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  color: var(--accent);
  padding: 1px 5px; border-radius: 4px;
}

.actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* Client-ID setup steps (collapsible numbered list) */
.client-id-steps {
  margin: 0; padding-left: 22px;
  display: flex; flex-direction: column; gap: 6px;
  font-size: 12.5px; color: var(--text-2); line-height: 1.55;
}
.client-id-steps li::marker { color: var(--text-3); }
.client-id-steps a {
  color: var(--accent); text-decoration: none; font-weight: 500;
}
.client-id-steps a:hover { text-decoration: underline; }
.client-id-steps strong {
  color: var(--text-1); font-weight: 600;
}
.client-id-steps pre.code {
  margin: 6px 0 0; padding: 8px 10px;
  font-family: var(--font-mono); font-size: 11.5px;
  background: var(--surface-2); color: var(--text-1);
  border-radius: 6px; border: 1px solid var(--border);
  white-space: pre; overflow-x: auto;
  user-select: all;
}

/* Inline Client-ID paste field */
.client-id-form {
  display: flex; flex-direction: column; gap: 8px;
  padding: 14px; border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.client-id-label {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px;
  font-size: 12px; font-weight: 600; color: var(--text-2);
  letter-spacing: 0.04em; text-transform: uppercase;
}
.client-id-toggle {
  background: none; border: none; padding: 0;
  font: inherit; font-size: 11px; font-weight: 500;
  color: var(--accent); text-transform: none; letter-spacing: 0;
  cursor: pointer;
}
.client-id-toggle:hover { color: var(--accent-2, var(--accent)); text-decoration: underline; }

.client-id-row { display: flex; gap: 8px; align-items: center; }
.client-id-row input {
  flex: 1; min-width: 0;
  padding: 8px 10px;
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px;
  font-family: var(--font-mono); font-size: 12.5px;
  color: var(--text-1); outline: none;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.client-id-row input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}

.btn-primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px; border-radius: 10px; border: none;
  background: linear-gradient(135deg, #1DB954, #1ed760);
  color: #0a0a0d; font: inherit; font-size: 13px; font-weight: 600;
  letter-spacing: -0.005em; cursor: pointer;
  box-shadow: 0 4px 12px color-mix(in srgb, #1DB954 26%, transparent);
  transition: transform 200ms cubic-bezier(0.32, 0.72, 0, 1),
              box-shadow 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.btn-primary:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px color-mix(in srgb, #1DB954 36%, transparent);
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-ghost {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: 10px;
  background: var(--surface-2); border: 1px solid var(--border);
  color: var(--text-2); font: inherit; font-size: 13px; font-weight: 500;
  cursor: pointer;
  transition: color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.btn-ghost.small { padding: 6px 12px; font-size: 12px; }
.btn-ghost:not(:disabled):hover { color: var(--text-1); border-color: var(--border-strong); }
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }

.fallback {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 12px;
}
.fallback-label {
  margin: 0 0 8px; font-size: 11.5px; color: var(--text-3);
}
.fallback-row { display: flex; gap: 6px; align-items: center; }
.fallback-row input {
  flex: 1; min-width: 0;
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px;
  font: inherit; font-size: 12px; font-family: var(--font-mono);
  color: var(--text-1); outline: none;
}
.fallback-row input:focus { border-color: var(--accent); }

.share-row {
  display: flex; align-items: flex-start; gap: 16px;
  padding: 14px 18px;
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}
.share-row > div { flex: 1; min-width: 0; }
.share-row strong {
  display: block; font-size: 13px; color: var(--text-1);
  font-weight: 600; letter-spacing: -0.005em;
}
.share-row .hint { margin-top: 4px; }

.switch { position: relative; flex-shrink: 0; cursor: pointer; }
.switch input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.switch .track {
  display: block; width: 38px; height: 22px; border-radius: 999px;
  background: var(--surface-1); border: 1px solid var(--border);
  transition: background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
  position: relative;
}
.switch .thumb {
  position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--text-3);
  transition: transform 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.switch input:checked + .track {
  background: color-mix(in srgb, var(--accent) 30%, var(--surface-1));
  border-color: var(--accent);
}
.switch input:checked + .track .thumb {
  transform: translateX(16px); background: var(--accent);
}

.error-msg {
  margin: 0 18px 16px;
  padding: 8px 12px; border-radius: 8px;
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
  color: var(--error); font-size: 12.5px;
}
</style>
