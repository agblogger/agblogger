import { useEffect, useState } from 'react'
import type { RefObject } from 'react'

export function useActiveHeading(contentRef: RefObject<HTMLElement | null>): string | null {
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    const container = contentRef.current
    if (!container) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id)
          }
        }
      },
      { rootMargin: '-112px 0px -60% 0px', threshold: 0 },
    )

    const observeHeadings = () => {
      observer.disconnect()
      const headings = container.querySelectorAll('h2, h3')
      if (headings.length === 0) {
        setActiveId(null)
        return
      }
      headings.forEach((heading) => observer.observe(heading))
    }

    observeHeadings()

    const mutationObserver = new MutationObserver(() => {
      observeHeadings()
    })
    mutationObserver.observe(container, { childList: true, subtree: true })

    return () => {
      mutationObserver.disconnect()
      observer.disconnect()
    }
  }, [contentRef])

  return activeId
}
