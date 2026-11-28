import { createContext, useContext } from 'react'

import type { Lang, MessageKey } from './messages'

export type Dir = 'ltr' | 'rtl'

export interface Formatters {
  /** 1234 -> "1,234" (Western digits in both languages). */
  number: (value: number) => string
  /** 0.423 -> "42%". */
  percent: (fraction: number) => string
  /** "14:00", 24-hour, in `timeZone` (default: this device's). */
  time: (iso: string, timeZone?: string) => string
  /** "26 Nov" for a YYYY-MM-DD day. */
  day: (isoDate: string) => string
  /** Short weekday name, 0 = Monday. */
  weekday: (mondayFirstIndex: number) => string
  /** For chat lists: "14:05" today, "Yesterday", else "26 Nov". */
  when: (iso: string, now?: Date) => string
}

export interface I18n {
  lang: Lang
  dir: Dir
  setLang: (lang: Lang) => void
  t: (key: MessageKey, vars?: Record<string, string | number>) => string
  fmt: Formatters
}

export const I18nContext = createContext<I18n | null>(null)

export function useI18n(): I18n {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside <I18nProvider>')
  return value
}

export function localeOf(lang: Lang): string {
  // -u-nu-latn keeps digits as 0-9 in Arabic too, which is what businesses in the UAE use.
  return lang === 'ar' ? 'ar-AE-u-nu-latn' : 'en-AE'
}

export function makeFormatters(lang: Lang, t: I18n['t']): Formatters {
  const locale = localeOf(lang)
  const numbers = new Intl.NumberFormat(locale)
  const percents = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
  const days = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', timeZone: 'UTC' })
  const weekdays = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' })
  const times = new Map<string, Intl.DateTimeFormat>()
  const timeIn = (timeZone?: string) => {
    const key = timeZone ?? ''
    let format = times.get(key)
    if (!format) {
      format = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
      times.set(key, format)
    }
    return format
  }
  const localDay = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`

  return {
    number: (value) => numbers.format(value),
    percent: (fraction) => percents.format(Number.isFinite(fraction) ? fraction : 0),
    time: (iso, timeZone) => timeIn(timeZone).format(new Date(iso)),
    day: (isoDate) => days.format(new Date(`${isoDate}T00:00:00Z`)),
    // 2024-01-01 was a Monday.
    weekday: (index) => weekdays.format(new Date(Date.UTC(2024, 0, 1 + index))),
    when: (iso, now = new Date()) => {
      const at = new Date(iso)
      if (localDay(at) === localDay(now)) return timeIn().format(at)
      const yesterday = new Date(now)
      yesterday.setDate(now.getDate() - 1)
      if (localDay(at) === localDay(yesterday)) return t('time.yesterday')
      return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' }).format(at)
    },
  }
}
