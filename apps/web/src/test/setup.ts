import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  try {
    window.localStorage.clear()
  } catch {
    // some tests make storage throw on purpose
  }
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.lang = 'en'
  document.documentElement.dir = 'ltr'
})

// Node 25+ has its own localStorage global, which is unusable without --localstorage-file and hides jsdom's.
// Use jsdom's, as a browser would.
const dom = (globalThis as { jsdom?: { window: Window } }).jsdom
if (dom) {
  for (const key of ['localStorage', 'sessionStorage'] as const) {
    Object.defineProperty(globalThis, key, { configurable: true, get: () => dom.window[key] })
  }
}

// jsdom has no ResizeObserver (Recharts' ResponsiveContainer uses it) and no matchMedia.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoopResizeObserver as unknown as typeof ResizeObserver
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
Element.prototype.scrollTo ??= () => {}
