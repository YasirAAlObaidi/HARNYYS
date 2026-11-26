import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'

import { readSetting, writeSetting } from '../lib/storage'
import { I18nContext, type I18n, makeFormatters } from './context'
import { type Lang, type MessageKey, messages } from './messages'

const STORAGE_KEY = 'yyai.lang'

function initialLang(): Lang {
  const saved = readSetting(STORAGE_KEY)
  if (saved === 'ar' || saved === 'en') return saved
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('ar') ? 'ar' : 'en'
}

/** The language and direction of the whole app. Sets <html lang dir>, so CSS logical properties mirror. */
export function I18nProvider({ children, lang: fixed }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(() => fixed ?? initialLang())
  const dir = lang === 'ar' ? 'rtl' : 'ltr'

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = dir
  }, [lang, dir])

  const setLang = useCallback((next: Lang) => {
    writeSetting(STORAGE_KEY, next)
    setLangState(next)
  }, [])

  const value = useMemo<I18n>(() => {
    const table = messages[lang]
    const t = (key: MessageKey, vars?: Record<string, string | number>) => {
      const text = table[key] ?? messages.en[key] ?? key
      return vars ? text.replace(/\{(\w+)\}/g, (match, name: string) => String(vars[name] ?? match)) : text
    }
    return { lang, dir, setLang, t, fmt: makeFormatters(lang, t) }
  }, [lang, dir, setLang])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}
