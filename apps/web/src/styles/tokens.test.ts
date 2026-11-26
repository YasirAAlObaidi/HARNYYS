/// <reference types="node" />
// Every text and UI colour pair in tokens.css meets WCAG 2.1 AA, in light and in dark:
// 4.5:1 for text, 3:1 for borders, chart marks and focus rings.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

// Read from disk (the test runner does not load CSS). Vitest runs from apps/web.
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`)
  if (start < 0) throw new Error(`no ${selector} block in tokens.css`)
  const body = css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start))
  const tokens: Record<string, string> = {}
  for (const match of body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\s*;/gi)) tokens[match[1]!] = match[2]!.toLowerCase()
  return tokens
}

const light = block(':root')
const dark = { ...light, ...block(":root[data-theme='dark']") }

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

const TEXT: [string, string][] = [
  ['text', 'bg'],
  ['text', 'surface'],
  ['text', 'surface-2'],
  ['text-muted', 'bg'],
  ['text-muted', 'surface'],
  ['text-muted', 'surface-2'],
  ['on-primary', 'primary'],
  ['on-primary', 'primary-hover'],
  ['accent-text', 'bg'],
  ['accent-text', 'surface'],
  ['accent-text', 'surface-2'],
  ['accent-text', 'bubble-ai'],
  ['accent-text', 'warning-bg'],
  ['header-text', 'header-bg'],
  ['header-muted', 'header-bg'],
  ['bubble-text', 'bubble-customer'],
  ['bubble-text', 'bubble-ai'],
  ['bubble-text', 'bubble-staff'],
  ['text-muted', 'bubble-customer'],
  ['text-muted', 'bubble-ai'],
  ['text-muted', 'bubble-staff'],
  ['success', 'bubble-staff'],
  ['danger', 'surface'],
  ['danger', 'danger-bg'],
  ['danger', 'bubble-ai'],
  ['text', 'warning-bg'],
]

const NON_TEXT: [string, string][] = [
  ['border-strong', 'surface'],
  ['border-strong', 'bg'],
  ['focus', 'surface'],
  ['focus', 'bg'],
  ['accent', 'header-bg'],
  ['chart-1', 'surface'],
  ['chart-2', 'surface'],
  ['chart-3', 'surface'],
  ['heat-1', 'surface'],
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
    expect(light['brand-gold']).toBe('#bb8f44') // KD-White.svg, the logo mark
    expect(light['brand-white']).toBe('#ffffff') // KD-White.svg, the wordmark
    expect(light['brand-green']).toBe('#1e4a23') // kahramandubai.com theme, behind the white logo
    expect(light['brand-charcoal']).toBe('#12171b')
  })

  it('the dark theme in the media query matches the [data-theme=dark] one', () => {
    const media = block(":root:not([data-theme='light'])")
    expect(media).toEqual(block(":root[data-theme='dark']"))
  })
})
