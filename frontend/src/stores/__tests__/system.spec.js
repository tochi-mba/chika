/**
 * Unit tests for the system Pinia store — pet state machine, settings,
 * connection state, autonomy.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSystemStore } from '../system.js'

describe('system store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts disconnected with no events', () => {
    const s = useSystemStore()
    expect(s.connected).toBe(false)
    expect(s.events).toEqual([])
  })

  it('setConnected toggles connection flag', () => {
    const s = useSystemStore()
    s.setConnected(true, 'sess-x')
    expect(s.connected).toBe(true)
    s.setConnected(false)
    expect(s.connected).toBe(false)
  })

  it('pet state goes working on workflow_start', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'workflow_start', workflow_id: 'wf' })
    expect(s.petState.state).toBe('working')
  })

  it('pet state goes celebrate on workflow_done', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'workflow_start' })
    s.pushEvent({ type: 'workflow_done', workflow_id: 'wf', variables: {} })
    expect(s.petState.state).toBe('celebrate')
  })

  it('pet state goes sad on error', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'error', message: 'boom' })
    expect(s.petState.state).toBe('sad')
  })

  it('pet bubble reflects the running tool', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'tool_call', tool: 'shell_exec' })
    expect(s.petState.bubble).toMatch(/command/)
  })

  it('settings_info populates autonomy', () => {
    const s = useSystemStore()
    s.pushEvent({
      type: 'settings_info',
      autonomy: 'autonomous',
      categories: {},
      tool_permissions: {},
    })
    expect(s.autonomy).toBe('autonomous')
  })
})
