/**
 * Unit tests for the chat Pinia store.
 *
 * Run: cd frontend && npm run test:unit
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat.js'

describe('chat store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts empty', () => {
    const s = useChatStore()
    expect(s.messages).toEqual([])
    expect(s.isStreaming).toBe(false)
  })

  it('addUserMessage pushes a user-role message', () => {
    const s = useChatStore()
    s.addUserMessage('hello')
    expect(s.messages.length).toBe(1)
    expect(s.messages[0].role).toBe('user')
    expect(s.messages[0].text).toBe('hello')
  })

  it('startAssistantMessage flips isStreaming and adds a placeholder', () => {
    const s = useChatStore()
    s.startAssistantMessage()
    expect(s.isStreaming).toBe(true)
    expect(s.messages[s.messages.length - 1].role).toBe('assistant')
    expect(s.messages[s.messages.length - 1].streaming).toBe(true)
  })

  it('appendToken concatenates onto the streaming bubble', () => {
    const s = useChatStore()
    s.startAssistantMessage()
    s.appendToken('Hello ')
    s.appendToken('world')
    const last = s.messages[s.messages.length - 1]
    expect(last.text).toBe('Hello world')
  })

  it('attachToolEvent flags tool_call as pending then flips on tool_result', () => {
    const s = useChatStore()
    s.startAssistantMessage()
    s.attachToolEvent({ type: 'tool_call', step_id: 's1', tool: 'echo' })
    let last = s.messages[s.messages.length - 1]
    expect(last.toolEvents.length).toBe(1)
    expect(last.toolEvents[0].pending).toBe(true)

    s.attachToolEvent({
      type: 'tool_result', step_id: 's1', tool: 'echo',
      result: { ok: true },
    })
    last = s.messages[s.messages.length - 1]
    const call = last.toolEvents.find((e) => e.type === 'tool_call')
    const res  = last.toolEvents.find((e) => e.type === 'tool_result')
    expect(call.pending).toBe(false)
    expect(res.result.ok).toBe(true)
  })

  it('attachToolEvent ignores events when no assistant bubble exists', () => {
    const s = useChatStore()
    // No startAssistantMessage call first.
    s.attachToolEvent({ type: 'tool_call', step_id: 's1', tool: 'x' })
    expect(s.messages.length).toBe(0)
  })

  it('appendThinking attaches reasoning to the active bubble', () => {
    const s = useChatStore()
    s.startAssistantMessage()
    s.appendThinking('reasoning… ')
    s.appendThinking('more reasoning.')
    const last = s.messages[s.messages.length - 1]
    expect(last.thinking).toBe('reasoning… more reasoning.')
  })

  it('finaliseAssistantMessage flips streaming off', () => {
    const s = useChatStore()
    s.startAssistantMessage()
    s.appendToken('done')
    s.finaliseAssistantMessage()
    expect(s.isStreaming).toBe(false)
    const last = s.messages[s.messages.length - 1]
    expect(last.streaming).toBe(false)
  })

  it('clear empties messages', () => {
    const s = useChatStore()
    s.addUserMessage('one')
    s.addUserMessage('two')
    s.clear()
    expect(s.messages).toEqual([])
  })

  it('setTitle stores the chat title', () => {
    const s = useChatStore()
    s.setTitle('My Chat')
    expect(s.title).toBe('My Chat')
  })

  it('restoreSession loads messages, title, sessionId', () => {
    const s = useChatStore()
    s.restoreSession({
      session_id: 'sess-1',
      title:      'Restored',
      messages:   [{ role: 'user', content: 'hi' }],
    })
    expect(s.sessionId).toBe('sess-1')
    expect(s.title).toBe('Restored')
    expect(s.messages.length).toBe(1)
  })
})
