import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'

import { readSetting, writeSetting } from '../lib/storage'
import { NEXT_THEME, type Theme, type ThemeChoice, ThemeContext } from './context'

const STORAGE_KEY = 'yyai.theme'

function savedChoice(): ThemeChoice {
  const saved = readSetting(STORAGE_KEY)
  return saved === 'light' || saved === 'dark' ? saved : 'system'
}

/**
 * Light and dark themes. With "system" there is no data-theme attribute and tokens.css follows
 * prefers-color-scheme; a chosen theme sets <html data-theme> and is remembered in localStorage.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(savedChoice)

  useEffect(() => {
    const root = document.documentElement
    if (choice === 'system') delete root.dataset.theme
    else root.dataset.theme = choice
  }, [choice])

  const setChoice = useCallback((next: ThemeChoice) => {
    writeSetting(STORAGE_KEY, next === 'system' ? null : next)
    setChoiceState(next)
  }, [])

  const value = useMemo<Theme>(
    () => ({ choice, setChoice, cycle: () => setChoice(NEXT_THEME[choice]) }),
    [choice, setChoice],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
