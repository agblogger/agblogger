import { useEffect } from 'react'
import type { RefObject } from 'react'

export function useHashScroll(
  ref: RefObject<HTMLElement | null>,
  html: string | null | undefined,
) {
  useEffect(() => {
    if (html == null || html === '' || !ref.current) return
    const hash = window.location.hash
    if (!hash) return
    const id = decodeURIComponent(hash.slice(1))
    const target = ref.current.querySelector(`#${CSS.escape(id)}`)
    target?.scrollIntoView({ block: 'start' })
  }, [html, ref])
}
