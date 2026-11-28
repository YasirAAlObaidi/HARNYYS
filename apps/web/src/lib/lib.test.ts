import { afterEach, describe, expect, it, vi } from 'vitest'

import { insightsRefetchMs } from '../api/queries'
import type { InsightSnapshot } from '../api/types'
import { normaliseCode, toWesternDigits } from './digits'
import { displayName, formatNumber, initial } from './people'
import { readSetting, writeSetting } from './storage'

describe('digits', () => {
  it('turns Eastern Arabic and Persian digits into 0-9', () => {
    expect(toWesternDigits('٠١٢٣٤٥٦٧٨٩')).toBe('0123456789')
    expect(toWesternDigits('۰۱۲۳۴۵۶۷۸۹')).toBe('0123456789')
    expect(toWesternDigits('كم سعر ١ كجم؟')).toBe('كم سعر 1 كجم؟')
  })

  it('reads a 6-digit code typed in either digit style, with spaces', () => {
    expect(normaliseCode('١٢٣ ٤٥٦')).toBe('123456')
    expect(normaliseCode(' 654321 ')).toBe('654321')
    expect(normaliseCode('12345')).toBeNull()
    expect(normaliseCode('12345a')).toBeNull()
  })
})

describe('storage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('remembers and forgets a setting', () => {
    writeSetting('yyai.test', 'dark')
    expect(readSetting('yyai.test')).toBe('dark')
    writeSetting('yyai.test', null)
    expect(readSetting('yyai.test')).toBeNull()
  })

  it('never throws when storage is blocked', () => {
    vi.spyOn(Object.getPrototypeOf(window.localStorage) as Storage, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Object.getPrototypeOf(window.localStorage) as Storage, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(readSetting('yyai.theme')).toBeNull()
    expect(() => writeSetting('yyai.theme', 'dark')).not.toThrow()
  })
})

describe('people', () => {
  it('shows the name, or the number with a plus', () => {
    expect(displayName({ customer_name: 'أحمد', external_user_id: '971501234567' })).toBe('أحمد')
    expect(displayName({ customer_name: null, external_user_id: '971501234567' })).toBe('+971501234567')
    expect(formatNumber('staff-1')).toBe('staff-1')
    expect(initial('+971501234567')).toBe('9')
    expect(initial('أحمد')).toBe('أ')
  })
})

describe('insights refresh', () => {
  const snapshot = { next_at: '2026-11-26T15:00:00+04:00' } as InsightSnapshot

  it('asks again a minute after the next hour', () => {
    const now = Date.parse('2026-11-26T14:30:00+04:00')
    expect(insightsRefetchMs(snapshot, now)).toBe(31 * 60_000)
  })

  it('asks every minute while the snapshot is missing or late', () => {
    expect(insightsRefetchMs(null)).toBe(60_000)
    expect(insightsRefetchMs(snapshot, Date.parse('2026-11-26T15:02:00+04:00'))).toBe(60_000)
  })
})
