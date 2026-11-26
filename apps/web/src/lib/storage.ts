// Remembered choices (theme, language). Storage can be blocked or missing (private windows, locked-down
// browsers), so every access is wrapped: the app then simply forgets the choice instead of breaking.

export function readSetting(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeSetting(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // Not remembered. Nothing else to do.
  }
}
