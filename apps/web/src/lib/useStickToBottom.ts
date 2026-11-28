import { useCallback, useLayoutEffect, useRef } from 'react'

const NEAR_BOTTOM_PX = 80

/**
 * Keeps a scrolling message list at the newest message as messages arrive, unless the reader has scrolled
 * up to read older ones. Returns the ref for the scrolling element and its onScroll handler.
 */
export function useStickToBottom<T extends HTMLElement>(count: number, resetKey: unknown) {
  const ref = useRef<T | null>(null)
  const stick = useRef(true)

  const onScroll = useCallback(() => {
    const element = ref.current
    if (element) stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < NEAR_BOTTOM_PX
  }, [])

  useLayoutEffect(() => {
    stick.current = true // a different chat starts at its newest message
  }, [resetKey])

  useLayoutEffect(() => {
    const element = ref.current
    if (element && stick.current) element.scrollTop = element.scrollHeight
  }, [count, resetKey])

  return { ref, onScroll }
}
