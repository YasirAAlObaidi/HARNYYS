import { createContext, useContext } from 'react'

/** "system" follows the device's light or dark setting; the other two override it. */
export type ThemeChoice = 'system' | 'light' | 'dark'

export interface Theme {
  choice: ThemeChoice
  setChoice: (choice: ThemeChoice) => void
  /** system -> light -> dark -> system */
  cycle: () => void
}

export const ThemeContext = createContext<Theme | null>(null)

export function useTheme(): Theme {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme must be used inside <ThemeProvider>')
  return value
}

export const NEXT_THEME: Record<ThemeChoice, ThemeChoice> = { system: 'light', light: 'dark', dark: 'system' }
