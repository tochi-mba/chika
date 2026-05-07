<template>
  <div v-if="open" class="settings-overlay" @click.self="$emit('close')">
    <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <header class="modal-header">
        <h2 id="settings-title">Settings</h2>
        <button class="close-btn" @click="$emit('close')" aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </header>

      <nav class="tabs">
        <button v-for="t in tabs" :key="t.id"
          class="tab" :class="{ active: tab === t.id }"
          @click="tab = t.id">{{ t.label }}</button>
      </nav>

      <!-- ── Provider tab ─────────────────────────────────────────────── -->
      <section v-if="tab === 'provider'" class="panel">
        <p class="hint">
          Switch the LLM provider and model. Changes are written to
          <code>.env</code> and <strong>require a server restart</strong>.
        </p>
        <div class="row">
          <label>Provider</label>
          <select v-model="draftProvider">
            <option v-for="p in providers" :key="p" :value="p">{{ p }}</option>
          </select>
        </div>
        <div class="row">
          <label>Model</label>
          <input v-model="draftModel" type="text" placeholder="e.g. claude-sonnet-4-6"/>
          <span class="muted small">env var: {{ modelVarFor(draftProvider) }}</span>
        </div>
        <div class="actions">
          <button class="primary" :disabled="provLoading || !providerDirty"
            @click="saveProvider">{{ provLoading ? 'Saving…' : 'Save' }}</button>
          <button @click="resetProvider">Reset</button>
        </div>
        <div v-if="provNotice" class="notice" :class="provNotice.kind">
          {{ provNotice.text }}
        </div>
      </section>

      <!-- ── Environment tab ──────────────────────────────────────────── -->
      <section v-else-if="tab === 'env'" class="panel">
        <div class="env-toolbar">
          <p class="hint">
            Edit <code>.env</code> directly. Secrets are masked by default.
            Boot-time vars (provider, API keys, ports) need a server restart
            to apply.
          </p>
          <label class="reveal-toggle">
            <input type="checkbox" v-model="showSecrets" @change="loadEnv"/>
            Reveal secrets
          </label>
        </div>

        <div class="env-list">
          <div v-for="(row, i) in envRows" :key="row.key" class="env-row">
            <input class="key" v-model="row.key" :readonly="!row.is_new" placeholder="KEY"/>
            <input class="val" v-model="row.value"
                   :type="row.is_secret && !showSecrets ? 'password' : 'text'"
                   :placeholder="row.is_secret ? '(secret)' : 'value'"/>
            <button class="row-btn delete" @click="removeRow(i)" title="Remove">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="actions">
          <button @click="addRow">+ Add variable</button>
          <button class="primary" :disabled="envLoading || !envDirty"
            @click="saveEnv">{{ envLoading ? 'Saving…' : 'Save .env' }}</button>
        </div>
        <div v-if="envNotice" class="notice" :class="envNotice.kind">
          {{ envNotice.text }}
        </div>
      </section>

      <!-- ── Pet tab ────────────────────────────────────────────────── -->
      <section v-else-if="tab === 'pet'" class="panel">
        <p class="hint">
          Pick a companion for this profile. The pet shows in the chat
          page and the CLI <code>/pet</code> command — switching here
          updates everywhere instantly.
        </p>

        <div class="pet-grid">
          <button
            v-for="p in petCatalogue"
            :key="p.id"
            class="pet-card"
            :class="{ active: activePetId === p.id }"
            :style="{ '--pet-accent': p.accent }"
            @click="choosePet(p.id)"
          >
            <span class="pet-card-emoji">{{ p.emoji || '🐾' }}</span>
            <span class="pet-card-name">{{ p.name }}</span>
            <span class="pet-card-desc">{{ p.description }}</span>
          </button>
        </div>

        <hr class="divider"/>

        <div class="row">
          <label class="row-label">LLM speech bubbles</label>
          <div class="speech-toggle">
            <button :class="{ active: petSpeech === 'off' }"
              @click="updatePetSpeech('off')">Off</button>
            <button :class="{ active: petSpeech === 'on' }"
              @click="updatePetSpeech('on')">On</button>
          </div>
        </div>
        <p class="hint">
          When on, the pet says one short LLM-generated quip per turn,
          fired in parallel so it doesn't slow your reply.
        </p>
        <div class="row" v-if="petSpeech === 'on'">
          <label class="row-label">Tokens per quip</label>
          <input type="number" min="8" max="200" v-model.number="petSpeechTokens"
                 @change="updatePetSpeechTokens"/>
        </div>
      </section>

      <!-- ── Behaviour tab ───────────────────────────────────────────── -->
      <section v-else-if="tab === 'behaviour'" class="panel">
        <p class="hint">
          Tune how chika behaves between turns — auto-continue, and the
          inline state indicator shown while the agent is thinking.
        </p>

        <h3 class="subhead">Auto-continue</h3>
        <div class="row">
          <label class="row-label">Mode</label>
          <div class="speech-toggle">
            <button :class="{ active: autoContinue === 'off' }"
              @click="updateAutoContinue('off')">Off</button>
            <button :class="{ active: autoContinue === 'on' }"
              @click="updateAutoContinue('on')">On</button>
          </div>
        </div>
        <p class="hint">
          When the agent ends a turn with "next, I'll …" and isn't asking a
          question, fire another turn so it actually does the next thing.
        </p>
        <div class="row" v-if="autoContinue === 'on'">
          <label class="row-label">Max hops per turn</label>
          <input type="number" min="1" max="50"
                 v-model.number="autoContinueMax"
                 @change="updateAutoContinueMax"/>
        </div>

        <hr class="divider"/>

        <h3 class="subhead">State indicator</h3>
        <div class="row">
          <label class="row-label">Context-aware verbs</label>
          <div class="speech-toggle">
            <button :class="{ active: stateVerbs === 'off' }"
              @click="updateStateVerbs('off')">Off</button>
            <button :class="{ active: stateVerbs === 'on' }"
              @click="updateStateVerbs('on')">On</button>
          </div>
        </div>
        <p class="hint">
          When on, chika fires a tiny LLM call each turn to generate
          verbs that fit the request ("Investigating", "Sketching", …)
          for the inline <code>◣ ▲ ◢ Thinking…</code> indicator.
          When off, a static rotation is used.
        </p>
        <div class="row" v-if="stateVerbs === 'on'">
          <label class="row-label">Tokens per call</label>
          <input type="number" min="16" max="200"
                 v-model.number="stateVerbsTokens"
                 @change="updateStateVerbsTokens"/>
        </div>
      </section>

      <!-- ── Permissions tab ─────────────────────────────────────────── -->
      <section v-else-if="tab === 'permissions'" class="panel">
        <p class="hint">
          Control whether the agent asks before invoking tools in each
          category. The global preset sets the default; per-category
          overrides take precedence.
        </p>
        <div class="preset">
          <button :class="{ active: system.autonomy === 'supervised' }"
            @click="setAutonomy('supervised')">Supervised</button>
          <button :class="{ active: system.autonomy === 'autonomous' }"
            @click="setAutonomy('autonomous')">Autonomous</button>
        </div>

        <div v-for="(label, cat) in system.permissionCategories" :key="cat" class="perm-row">
          <span class="perm-label">{{ label }}</span>
          <div class="perm-toggle">
            <button :class="{ active: effectivePerm(cat) === 'ask' }"
              @click="setPerm(cat, 'ask')">Ask</button>
            <button :class="{ active: effectivePerm(cat) === 'skip' }"
              @click="setPerm(cat, 'skip')">Skip</button>
          </div>
        </div>
      </section>

      <!-- ── Skills tab ──────────────────────────────────────────────── -->
      <section v-else-if="tab === 'skills'" class="panel skills-panel">
        <p class="hint">
          Toggle skills on or off. Disabled skills aren't loaded into the
          agent's prompt and their tools are hidden — re-enable any time;
          changes apply on your next message, no restart required.
        </p>

        <div v-if="skillsLoading" class="skills-loading">Loading skills…</div>

        <div v-else class="skills-list">
          <div v-for="s in skills" :key="s.name"
               class="skill-row"
               :class="{ disabled: s.disabled }">
            <div class="skill-meta">
              <div class="skill-head">
                <span class="skill-name">{{ s.name }}</span>
                <span class="skill-tool-count">{{ (s.tools || []).length }} tool{{ (s.tools || []).length === 1 ? '' : 's' }}</span>
                <span v-if="s.disabled" class="skill-chip">off</span>
              </div>
              <div class="skill-desc" v-if="s.description">{{ s.description }}</div>
              <div class="skill-tools" v-if="s.tools && s.tools.length">
                <code v-for="t in s.tools.slice(0, 6)" :key="t.name || t">{{ t.name || t }}</code>
                <span v-if="s.tools.length > 6" class="muted small">+{{ s.tools.length - 6 }} more</span>
              </div>
            </div>
            <button class="skill-toggle"
                    :class="{ on: !s.disabled }"
                    @click="toggleSkill(s.name)"
                    :aria-pressed="!s.disabled"
                    :aria-label="`Toggle ${s.name} skill`">
              <span class="skill-toggle-knob"/>
            </button>
          </div>
        </div>

        <div v-if="skillsNotice" class="notice" :class="skillsNotice.kind">
          {{ skillsNotice.text }}
        </div>
      </section>

      <!-- ── Skill-owned dynamic tabs ──────────────────────────────────
           Every skill that ships a SKILL_UI manifest contributes its
           own tab here. The manifest is fetched from /api/skills/ui;
           the Vue component is statically discoverable via
           import.meta.glob over chika/skills/*/ui/*.vue at build time
           so there's no runtime evaluation. Drop a skill folder with
           a ui/ directory + SKILL_UI manifest, and a settings tab
           appears here on the next reload — no edits required.       -->
      <section v-for="dyn in skillTabs" :key="dyn.skill"
               v-show="tab === `skill:${dyn.skill}`"
               class="panel skill-dynamic-panel">
        <component
          :is="resolveSkillComponent(dyn.skill)"
          :api-key="apiKey"
          @patch-settings="(p) => emit('patch-settings', p)"
        />
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, shallowRef } from 'vue'
import { useSystemStore } from '../stores/system'

const props = defineProps({
  open:        { type: Boolean, default: false },
  apiKey:      { type: String, default: '' },
  initialTab:  { type: String, default: 'provider' },
})
const emit = defineEmits(['close', 'patch-settings'])

const system = useSystemStore()

// Static tabs (core platform — not skill-owned). Skill-contributed
// tabs are appended dynamically below from /api/skills/ui.
const staticTabs = [
  { id: 'provider',    label: 'Provider' },
  { id: 'env',         label: 'Environment' },
  { id: 'permissions', label: 'Permissions' },
  { id: 'behaviour',   label: 'Behaviour' },
  { id: 'skills',      label: 'Skills' },
]

// Dynamically-contributed tabs from the skill UI manifest. Each entry
// drives the {id: "skill:<name>", label} pair shown in the tab bar
// AND the <component :is> render in the panel section.
const skillTabs = ref([])  // [{ skill, label, order, frontend, extension }]

// Eager static-bundled map of every Vue component shipped under
// chika/skills/*_skill/ui/*.vue. Vite resolves the glob at build time
// — at runtime this is just a {path: module} dict.
const _skillComponents = import.meta.glob(
  '../../../chika/skills/*_skill/ui/*.vue',
  { eager: true },
)

function resolveSkillComponent(skillName) {
  // Match the bundled component for this skill. The path shape is:
  //   ../../../chika/skills/<name>_skill/ui/<File>.vue
  // We pick whichever .vue lives under the right folder — most skills
  // ship a single SettingsCard.vue but we don't hardcode the filename.
  const prefix = `../../../chika/skills/${skillName}_skill/ui/`
  for (const [path, mod] of Object.entries(_skillComponents)) {
    if (path.startsWith(prefix)) {
      return mod.default || mod
    }
  }
  return null
}

const tabs = computed(() => [
  ...staticTabs,
  ...skillTabs.value.map(s => ({ id: `skill:${s.skill}`, label: s.label })),
])

async function loadSkillTabs() {
  try {
    const res = await fetch(buildApiUrl('/api/skills/ui'), { headers: authHeaders() })
    if (!res.ok) return
    const data = await res.json()
    skillTabs.value = data.tabs || []
  } catch {/* silent — the rest of settings still works without skill tabs */}
}
const tab = ref(props.initialTab || 'provider')
watch(() => props.initialTab, (v) => { if (v) tab.value = v })

// ── Auth helpers ──────────────────────────────────────────────────────────

function buildApiUrl(path) {
  const base = typeof __API_URL__ !== 'undefined' && __API_URL__
    ? __API_URL__
    : `${location.protocol}//${location.host}`
  return `${base.replace(/\/$/, '')}${path}`
}

function authHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra }
  const k = props.apiKey || localStorage.getItem('chika_api_key') || ''
  if (k) h['Authorization'] = `Bearer ${k}`
  return h
}

// ── Provider tab ──────────────────────────────────────────────────────────

const providers = ref(['anthropic', 'openai', 'azure', 'ollama'])
const serverProvider = ref('')
const serverModel = ref('')
const draftProvider = ref('')
const draftModel = ref('')
const provLoading = ref(false)
const provNotice = ref(null)

const providerDirty = computed(() =>
  draftProvider.value !== serverProvider.value || draftModel.value !== serverModel.value
)

function modelVarFor(p) {
  return ({
    anthropic: 'ANTHROPIC_MODEL',
    openai:    'OPENAI_MODEL',
    azure:     'AZURE_OPENAI_DEPLOYMENT',
    ollama:    'OLLAMA_MODEL',
  })[p] || ''
}

async function loadProvider() {
  try {
    const res = await fetch(buildApiUrl('/api/provider'), { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    serverProvider.value = data.provider
    serverModel.value    = data.model
    draftProvider.value  = data.provider
    draftModel.value     = data.model
    if (Array.isArray(data.providers)) providers.value = data.providers
  } catch (err) {
    provNotice.value = { kind: 'error', text: `Failed to load provider: ${err.message}` }
  }
}

async function saveProvider() {
  provLoading.value = true
  provNotice.value = null
  try {
    const res = await fetch(buildApiUrl('/api/provider'), {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({
        provider: draftProvider.value,
        model:    draftModel.value,
      }),
    })
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`)
    const data = await res.json().catch(() => ({}))
    serverProvider.value = draftProvider.value
    serverModel.value    = draftModel.value
    // Hot-reload made restart unnecessary. The backend still returns a
    // ``hot_reload`` summary so we can surface per-session errors
    // (e.g., missing API key for the new provider) instead of silently
    // pretending the swap worked.
    const errs = (data?.hot_reload?.errors) || []
    if (errs.length) {
      provNotice.value = {
        kind: 'error',
        text: `Saved to .env, but the live swap had errors: ${errs.join('; ')}`,
      }
    } else {
      provNotice.value = {
        kind: 'success',
        text: '✓ Switched live — your next message uses the new provider.',
      }
    }
  } catch (err) {
    provNotice.value = { kind: 'error', text: `Save failed: ${err.message}` }
  } finally {
    provLoading.value = false
  }
}

function resetProvider() {
  draftProvider.value = serverProvider.value
  draftModel.value    = serverModel.value
  provNotice.value = null
}

// ── Environment tab ───────────────────────────────────────────────────────

const showSecrets = ref(false)
const envRows = ref([])  // [{ key, value, is_secret, is_new }]
const envSnapshot = ref([])
const envLoading = ref(false)
const envNotice = ref(null)

const envDirty = computed(() => {
  if (envRows.value.length !== envSnapshot.value.length) return true
  for (let i = 0; i < envRows.value.length; i++) {
    const a = envRows.value[i], b = envSnapshot.value[i]
    if (!b || a.key !== b.key || a.value !== b.value) return true
  }
  return false
})

async function loadEnv() {
  try {
    const url = buildApiUrl('/api/env') + (showSecrets.value ? '?show_secrets=1' : '')
    const res = await fetch(url, { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    envRows.value = (data.vars || []).map(v => ({ ...v, is_new: false }))
    envSnapshot.value = envRows.value.map(v => ({ ...v }))
  } catch (err) {
    envNotice.value = { kind: 'error', text: `Failed to load .env: ${err.message}` }
  }
}

function addRow() {
  envRows.value.push({ key: '', value: '', is_secret: false, is_new: true })
}

function removeRow(i) {
  envRows.value.splice(i, 1)
}

async function saveEnv() {
  envLoading.value = true
  envNotice.value = null
  try {
    // Compute diff vs snapshot
    const set = {}
    const unset = []
    const snapMap = Object.fromEntries(envSnapshot.value.map(r => [r.key, r]))
    const newKeys = new Set()
    for (const row of envRows.value) {
      const key = row.key.trim()
      if (!key) continue
      newKeys.add(key)
      const prev = snapMap[key]
      // For secrets the masked value loops back; only write when a value
      // looks fresh (changed AND not just the same masked placeholder).
      if (!prev) {
        set[key] = row.value
      } else if (row.value !== prev.value) {
        set[key] = row.value
      }
    }
    for (const r of envSnapshot.value) {
      if (!newKeys.has(r.key)) unset.push(r.key)
    }

    if (Object.keys(set).length === 0 && unset.length === 0) {
      envNotice.value = { kind: 'info', text: 'No changes to save.' }
      return
    }

    const res = await fetch(buildApiUrl('/api/env'), {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ set, unset }),
    })
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`)
    const data = await res.json()
    envRows.value = (data.vars || []).map(v => ({ ...v, is_new: false }))
    envSnapshot.value = envRows.value.map(v => ({ ...v }))
    envNotice.value = {
      kind: 'success',
      text: data.restart_required
        ? 'Saved. Restart the server for the change to apply.'
        : 'Saved.',
    }
  } catch (err) {
    envNotice.value = { kind: 'error', text: `Save failed: ${err.message}` }
  } finally {
    envLoading.value = false
  }
}

// ── Pet tab ──────────────────────────────────────────────────────────────

const petCatalogue   = ref([])
const activePetId    = ref(null)
const petSpeech      = ref('off')
const petSpeechTokens = ref(40)

// Behaviour tab — auto-continue + state-indicator settings.
const autoContinue     = ref('on')
const autoContinueMax  = ref(10)
const stateVerbs       = ref('on')
const stateVerbsTokens = ref(80)

async function loadPets() {
  try {
    const res = await fetch(buildApiUrl('/api/pets'), { headers: authHeaders() })
    if (res.ok) {
      const d = await res.json()
      petCatalogue.value = d.pets || []
    }
  } catch {/* silent */}

  try {
    const profileName = system.profile?.name || 'default'
    const res2 = await fetch(buildApiUrl(`/api/profile/${profileName}/pet`),
                             { headers: authHeaders() })
    if (res2.ok) {
      const d = await res2.json()
      activePetId.value = d.pet_id
    }
  } catch {/* silent */}

  try {
    const res3 = await fetch(buildApiUrl('/api/settings'), { headers: authHeaders() })
    if (res3.ok) {
      const d = await res3.json()
      petSpeech.value = d.pet_speech || 'off'
      petSpeechTokens.value = d.pet_speech_tokens || 40
      // Behaviour tab values.
      autoContinue.value     = d.auto_continue       || 'on'
      autoContinueMax.value  = d.auto_continue_max   || 10
      stateVerbs.value       = d.state_verbs         || 'on'
      stateVerbsTokens.value = d.state_verbs_tokens  || 80
    }
  } catch {/* silent */}
}

async function choosePet(id) {
  const profileName = system.profile?.name || 'default'
  try {
    const res = await fetch(buildApiUrl(`/api/profile/${profileName}/pet`), {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ pet_id: id }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    activePetId.value = id
    // The server broadcasts pet_changed to all sessions — store updates itself.
  } catch (err) {
    console.error('[Pet] choosePet failed:', err)
  }
}

function updatePetSpeech(val) {
  petSpeech.value = val
  emit('patch-settings', { pet_speech: val })
}

function updatePetSpeechTokens() {
  const n = Math.max(8, Math.min(200, parseInt(petSpeechTokens.value) || 40))
  petSpeechTokens.value = n
  emit('patch-settings', { pet_speech_tokens: n })
}

// ── Behaviour tab handlers ─────────────────────────────────────────────
function updateAutoContinue(val) {
  autoContinue.value = val
  emit('patch-settings', { auto_continue: val })
}
function updateAutoContinueMax() {
  const n = Math.max(1, Math.min(50, parseInt(autoContinueMax.value) || 10))
  autoContinueMax.value = n
  emit('patch-settings', { auto_continue_max: n })
}
function updateStateVerbs(val) {
  stateVerbs.value = val
  emit('patch-settings', { state_verbs: val })
}
function updateStateVerbsTokens() {
  const n = Math.max(16, Math.min(200, parseInt(stateVerbsTokens.value) || 80))
  stateVerbsTokens.value = n
  emit('patch-settings', { state_verbs_tokens: n })
}

watch(() => props.open, (v) => {
  if (v && tab.value === 'pet') loadPets()
})
watch(tab, (t) => { if (t === 'pet') loadPets() })

// ── Skills tab ───────────────────────────────────────────────────────────

const skills = ref([])               // [{ name, description, tools, disabled }]
const skillsDisabled = ref([])       // mirrors settings.skills_disabled
const skillsLoading = ref(false)
const skillsNotice = ref(null)

async function loadSkills() {
  skillsLoading.value = true
  skillsNotice.value = null
  try {
    const res = await fetch(buildApiUrl('/api/skills'), { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    skills.value = data.skills || []
    skillsDisabled.value = data.disabled || []
  } catch (err) {
    skillsNotice.value = { kind: 'error', text: `Failed to load skills: ${err.message}` }
  } finally {
    skillsLoading.value = false
  }
}

async function toggleSkill(name) {
  const cur = new Set(skillsDisabled.value)
  if (cur.has(name)) cur.delete(name)
  else cur.add(name)
  const next = Array.from(cur)

  // Optimistic update — flip the row immediately, revert on failure.
  const prevSkills = skills.value
  const prevDisabled = skillsDisabled.value
  skillsDisabled.value = next
  skills.value = skills.value.map(s =>
    s.name === name ? { ...s, disabled: cur.has(name) } : s
  )

  try {
    const res = await fetch(buildApiUrl('/api/settings'), {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ skills_disabled: next }),
    })
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`)
    skillsNotice.value = {
      kind: 'success',
      text: cur.has(name)
        ? `${name} disabled — hidden from the next turn.`
        : `${name} re-enabled.`,
    }
    // Re-fetch to pick up the post-reload tool counts (a re-enabled
    // skill's tools weren't on the engine until reload_skills() ran).
    loadSkills()
  } catch (err) {
    // Revert
    skills.value = prevSkills
    skillsDisabled.value = prevDisabled
    skillsNotice.value = { kind: 'error', text: `Toggle failed: ${err.message}` }
  }
}

watch(tab, (t) => { if (t === 'skills') loadSkills() })

// ── Permissions tab ──────────────────────────────────────────────────────

function effectivePerm(cat) {
  const explicit = system.toolPermissions[cat]
  if (explicit) return explicit
  return system.autonomy === 'autonomous' ? 'skip' : 'ask'
}

function setAutonomy(val)         { emit('patch-settings', { autonomy: val }) }
function setPerm(cat, perm)       { emit('patch-settings', { tool_permissions: { [cat]: perm } }) }

// Auto-load when modal opens
watch(() => props.open, (v) => {
  if (v) {
    loadProvider()
    loadEnv()
    loadSkillTabs()
  }
}, { immediate: true })
</script>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(11, 12, 16, 0.7);
  z-index: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.settings-modal {
  background: var(--surface-1);
  border: 1px solid var(--border-strong, rgba(255, 255, 255, 0.10));
  border-radius: 14px;
  width: min(720px, 100%);
  max-height: min(720px, 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.55);
  animation: settings-pop 200ms cubic-bezier(0.32, 0.72, 0, 1);
}

@keyframes settings-pop {
  from { transform: scale(0.97) translateY(8px); opacity: 0; }
  to   { transform: scale(1)    translateY(0);   opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}
.modal-header h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: -0.015em;
}
.close-btn {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 4px;
  display: flex;
  border-radius: var(--radius-sm);
  transition: color 120ms, background 120ms;
}
.close-btn:hover { color: var(--text-1); background: var(--surface-2); }

.tabs {
  display: flex;
  gap: 4px;
  padding: 0 22px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
}
.tabs::-webkit-scrollbar { display: none; }
.tab {
  background: none;
  border: none;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-3);
  padding: 12px 14px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
  margin-bottom: -1px;
  white-space: nowrap;
}
.tab:hover { color: var(--text-2); }
.tab.active {
  color: var(--text-1);
  border-bottom-color: var(--accent);
}

.panel {
  padding: 22px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}
.hint code {
  font-family: var(--font-mono);
  background: var(--surface-2);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
}

.row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row label {
  font-size: 11px;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.row select,
.row input,
.env-row .key,
.env-row .val {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-1);
  outline: none;
  transition: border-color 120ms;
}
.row select:focus,
.row input:focus,
.env-row .key:focus,
.env-row .val:focus {
  border-color: var(--accent);
}

.muted { color: var(--text-3); }
.small { font-size: 11px; }

.actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.actions button {
  font: inherit;
  font-size: 12px;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-2);
  border-radius: var(--radius-sm);
  padding: 6px 12px;
  cursor: pointer;
  transition: all 120ms;
}
.actions button:hover { color: var(--text-1); border-color: var(--border-strong); }
.actions button.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}
.actions button.primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.env-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.reveal-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
}

.env-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 380px;
  overflow-y: auto;
  padding: 2px;
}
.env-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 2fr auto;
  gap: 6px;
  align-items: center;
}
.env-row .key { font-weight: 500; }
.env-row .val { letter-spacing: 0.02em; }
.row-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-3);
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 120ms, border-color 120ms;
}
.row-btn:hover { color: var(--red); border-color: var(--red); }

.notice {
  font-size: 12px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}
.notice.success { color: var(--green); border-color: var(--green); background: var(--green-dim); }
.notice.error   { color: var(--red);   border-color: var(--red);   background: var(--red-dim); }
.notice.info    { color: var(--text-2); }

/* Pet tab */
.pet-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}
.pet-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: all 160ms var(--ease);
}
.pet-card:hover {
  transform: translateY(-2px);
  border-color: var(--pet-accent);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}
.pet-card.active {
  border-color: var(--pet-accent);
  box-shadow: 0 0 0 2px var(--pet-accent) inset, 0 0 24px var(--pet-accent);
  background: var(--surface-1);
}
.pet-card-emoji {
  font-size: 28px;
  line-height: 1;
}
.pet-card-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: -0.01em;
}
.pet-card-desc {
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.35;
}

.divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 8px 0;
}

.row-label {
  font-size: 11px;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
}
.speech-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  width: max-content;
}
.speech-toggle button {
  background: none;
  border: none;
  font: inherit;
  font-size: 12px;
  color: var(--text-3);
  padding: 5px 14px;
  cursor: pointer;
  transition: all 100ms;
}
.speech-toggle button + button {
  border-left: 1px solid var(--border);
}
.speech-toggle button:hover { color: var(--text-2); background: var(--surface-2); }
.speech-toggle button.active {
  color: var(--accent);
  background: var(--accent-dim);
}

/* Permissions */
.preset {
  display: flex;
  gap: 6px;
}
.preset button {
  flex: 1;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-2);
  font: inherit;
  font-size: 12px;
  padding: 7px 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 120ms;
}
.preset button:hover { color: var(--text-1); border-color: var(--border-strong); }
.preset button.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

.perm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.perm-row:last-of-type { border-bottom: none; }
.perm-label { font-size: 12px; color: var(--text-2); flex: 1; }
.perm-toggle { display: flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.perm-toggle button {
  background: none; border: none; font: inherit; font-size: 11px;
  color: var(--text-3); padding: 3px 10px; cursor: pointer;
  transition: all 100ms;
}
.perm-toggle button + button { border-left: 1px solid var(--border); }
.perm-toggle button:hover { color: var(--text-2); background: var(--surface-2); }
.perm-toggle button.active { color: var(--accent); background: var(--accent-dim); }

/* Skills tab */
.skills-loading {
  font-size: 12px;
  color: var(--text-3);
  padding: 8px 0;
}
.skills-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.skill-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  transition: opacity 160ms var(--ease), border-color 160ms var(--ease);
}
.skill-row:hover { border-color: var(--border-strong, rgba(255, 255, 255, 0.10)); }
.skill-row.disabled { opacity: 0.55; }
.skill-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.skill-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.skill-name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: -0.01em;
}
.skill-tool-count {
  font-size: 10.5px;
  color: var(--text-3);
}
.skill-chip {
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-1);
  color: var(--text-3);
  border: 1px solid var(--border);
}
.skill-desc {
  font-size: 11.5px;
  color: var(--text-2);
  line-height: 1.45;
}
.skill-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}
.skill-tools code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
}
.skill-toggle {
  flex-shrink: 0;
  width: 34px;
  height: 20px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-1);
  cursor: pointer;
  padding: 0;
  position: relative;
  transition: background 160ms var(--ease), border-color 160ms var(--ease);
}
.skill-toggle:hover { border-color: var(--border-strong, rgba(255, 255, 255, 0.10)); }
.skill-toggle.on {
  background: var(--accent);
  border-color: var(--accent);
}
.skill-toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-2);
  transition: transform 160ms var(--ease), background 160ms var(--ease);
}
.skill-toggle.on .skill-toggle-knob {
  transform: translateX(14px);
  background: white;
}
</style>
