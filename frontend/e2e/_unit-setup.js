/**
 * Vitest setup file — runs once before all unit specs.
 *
 * Stubs the WebSocket and fetch APIs in jsdom so component-level tests
 * never make real network calls. Component tests should use
 * @vue/test-utils' mount() and pull stores from pinia.
 */
import { config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

class MockWS {
  constructor() {
    this.readyState = 1
    setTimeout(() => this.onopen && this.onopen({}), 0)
  }
  send() {}
  close() {}
  addEventListener(name, fn) { this['on' + name] = fn }
  removeEventListener() {}
}
MockWS.OPEN = 1
MockWS.CLOSED = 3

globalThis.WebSocket = MockWS
globalThis.fetch = async () =>
  new Response(JSON.stringify({}), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })

beforeEach(() => {
  setActivePinia(createPinia())
})

config.global.config.warnHandler = () => {}  // silence dev-mode prop warnings
