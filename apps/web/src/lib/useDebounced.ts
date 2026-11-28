import { useEffect, useState } from 'react'

/** `value`, but only after it has stopped changing for `delayMs` (so typing in a search box sends one request). */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return settled
}
