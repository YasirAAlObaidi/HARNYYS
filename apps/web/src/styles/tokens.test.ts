/// <reference types="node" />
// Every text and UI colour pair in tokens.css meets WCAG 2.1 AA, in light and in dark:
// 4.5:1 for text, 3:1 for control edges, focus rings, indicators and chart marks.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

// Read from disk (the test runner does not load CSS). Vitest runs from apps/web.
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

function block(marker: string): Record<string, string> {
  const start = css.indexOf(`/* ${marker} */`)
  if (start < 0) throw new Error(`no ${marker} block in tokens.css`)
  const open = css.indexOf('{', start)
  const body = css.slice(open + 1, css.indexOf('}', open))
  const tokens: Record<string, string> = {}
  for (const match of body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\s*;/gi)) tokens[match[1]!] = match[2]!.toLowerCase()
  return tokens
}

const light = block('@light')
const dark = { ...light, ...block('@dark') }

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi! + 0.05) / (lo! + 0.05)
}

const SURFACES = ['bg-canvas', 'bg-surface', 'bg-raised', 'bg-overlay']

const TEXT: [string, string][] = [
  ...SURFACES.map((bg): [string, string] => ['text-primary', bg]),
  ...SURFACES.map((bg): [string, string] => ['text-secondary', bg]),
  ...SURFACES.map((bg): [string, string] => ['text-muted', bg]),
  ['text-primary', 'bg-sunken'],
  ['text-muted', 'bg-sunken'],
  ['text-primary', 'bg-selected'],
  ['text-secondary', 'bg-selected'],
  ['action-primary-fg', 'action-primary-bg'],
  ['action-primary-fg', 'action-primary-hover'],
  ['action-secondary-fg', 'action-secondary-bg'],
  ['accent-gold-ink', 'bg-canvas'],
  ['accent-gold-ink', 'bg-surface'],
  ['accent-gold-ink', 'bg-raised'],
  ['accent-gold-ink', 'accent-gold-subtle'],
  ['text-primary', 'accent-gold-subtle'],
  ['text-primary', 'bubble-in-bg'],
  ['text-primary', 'bubble-out-bg'],
  ['text-primary', 'bubble-note-bg'],
  ['bubble-meta', 'bubble-in-bg'],
  ['bubble-meta', 'bubble-out-bg'],
  ['bubble-meta', 'bubble-note-bg'],
  ['nav-fg', 'nav-bg'],
  ['nav-fg', 'nav-hover'],
  ['nav-fg', 'nav-selected'],
  ['nav-fg-muted', 'nav-bg'],
  ['text-link', 'bg-canvas'],
  ['text-link', 'bg-surface'],
  ['success-fg', 'success-bg'],
  ['warning-fg', 'warning-bg'],
  ['danger-fg', 'danger-bg'],
  ['danger-fg', 'bg-surface'],
]

const NON_TEXT: [string, string][] = [
  ['border-strong', 'bg-canvas'],
  ['border-strong', 'bg-surface'],
  ['border-strong', 'bg-raised'],
  ['focus-ring', 'bg-canvas'],
  ['focus-ring', 'bg-surface'],
  ['focus-ring', 'bg-raised'],
  ['focus-ring-on-nav', 'nav-bg'],
  ['nav-indicator', 'nav-bg'],
  ['action-primary-bg', 'bg-surface'],
  ['chart-1', 'chart-surface'],
  ['chart-2', 'chart-surface'],
  ['chart-3', 'chart-surface'],
  ['heat-7', 'chart-surface'],
]

describe.each([
  ['light', light],
  ['dark', dark],
])('%s theme', (_name, tokens) => {
  it.each(TEXT)('text %s on %s is at least 4.5:1', (fg, bg) => {
    expect(tokens[fg], fg).toBeDefined()
    expect(tokens[bg], bg).toBeDefined()
    expect(contrast(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(4.5)
  })

  it.each(NON_TEXT)('%s on %s is at least 3:1', (fg, bg) => {
    expect(contrast(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(3)
  })
})

describe('brand colours', () => {
  it('are the exact colours of the Kahraman logo and site', () => {
    expect(light['kh-gold-500']).toBe('#bb8f44') // the logo mark
    expect(light['kh-white']).toBe('#ffffff') // the logo wordmark
    expect(light['kh-green-700']).toBe('#1e4a23') // their site, behind the white logo
    expect(light['kh-charcoal']).toBe('#12171b')
  })

  it('brand gold is never text on light: gold text uses the darker ink', () => {
    expect(contrast(light['kh-gold-500']!, light['bg-raised']!)).toBeLessThan(4.5)
    expect(contrast(light['accent-gold-ink']!, light['bg-raised']!)).toBeGreaterThanOrEqual(4.5)
  })

  it('the dark theme in the media query matches the [data-theme=dark] one', () => {
    expect(block('@dark-system')).toEqual(block('@dark'))
  })
})
