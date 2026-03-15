import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { List } from 'lucide-react'
import { useActiveHeading } from '@/hooks/useActiveHeading'

interface HeadingEntry {
  id: string
  text: string
  level: number
}

function extractHeadings(container: HTMLElement): HeadingEntry[] {
  const entries: HeadingEntry[] = []
  container.querySelectorAll('h2, h3').forEach((el) => {
    entries.push({
      id: el.id,
      text: el.textContent,
      level: el.tagName === 'H2' ? 2 : 3,
    })
  })
  return entries
}

interface TableOfContentsProps {
  contentRef: RefObject<HTMLElement | null>
  variant?: 'dropdown' | 'sidebar'
}

export default function TableOfContents({ contentRef, variant = 'dropdown' }: TableOfContentsProps) {
  const [headings, setHeadings] = useState<HeadingEntry[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const activeId = useActiveHeading(contentRef)

  useEffect(() => {
    const container = contentRef.current
    if (!container) return

    const observer = new MutationObserver(() => {
      setHeadings(extractHeadings(container))
    })

    setHeadings(extractHeadings(container))
    observer.observe(container, { childList: true, subtree: true })

    return () => observer.disconnect()
  }, [contentRef])

  useEffect(() => {
    if (!isOpen) return

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setIsOpen(false)
      }
    }

    function handleMouseDown(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    document.addEventListener('mousedown', handleMouseDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handleMouseDown)
    }
  }, [isOpen])

  if (headings.length < 3) return null

  if (variant === 'sidebar') {
    return (
      <nav className="sticky top-32 max-h-[calc(100vh-10rem)] overflow-y-auto" aria-label="Table of contents">
        <h3 className="font-display text-sm text-ink mb-3">On this page</h3>
        <ul className="space-y-1 border-l border-border pl-3">
          {headings.map((heading, index) => {
            const isActive = activeId === heading.id
            return (
              <li key={`${heading.id}-${index}`} className={heading.level === 3 ? 'pl-3' : ''}>
                <button
                  onClick={() =>
                    document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth' })
                  }
                  className={`block w-full text-left py-1 text-sm transition-colors ${
                    isActive
                      ? 'text-accent font-medium border-l-2 border-accent -ml-[calc(0.75rem+1px)] pl-[calc(0.75rem-1px)]'
                      : 'text-muted hover:text-ink'
                  }`}
                >
                  {heading.text}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>
    )
  }

  function handleLinkClick(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
    setIsOpen(false)
  }

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        aria-label="Table of contents"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors"
      >
        <List size={18} />
      </button>

      <div
        ref={panelRef}
        aria-hidden={!isOpen}
        className={`absolute right-0 top-full mt-2 w-72 bg-paper border border-border rounded-xl shadow-lg z-50 transition-all duration-200 ${
          isOpen
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 -translate-y-2 pointer-events-none'
        }`}
      >
        <div className="px-4 py-3 border-b border-border">
          <h3 className="font-display text-base text-ink">Table of Contents</h3>
        </div>
        <nav className="px-2 py-2 max-h-80 overflow-y-auto">
          <ul className="space-y-0.5">
            {headings.map((heading, index) => {
              const isActive = activeId === heading.id
              return (
                <li
                  key={`${heading.id}-${index}`}
                  className={heading.level === 3 ? 'pl-4' : ''}
                >
                  <button
                    onClick={() => handleLinkClick(heading.id)}
                    tabIndex={isOpen ? 0 : -1}
                    className={`block w-full text-left px-2 py-1.5 rounded-lg transition-colors ${
                      heading.level === 3 ? 'text-xs' : 'text-sm'
                    } ${
                      isActive
                        ? 'text-accent font-medium bg-paper-warm'
                        : 'text-muted hover:text-ink hover:bg-paper-warm/60'
                    }`}
                  >
                    {heading.text}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>
      </div>
    </div>
  )
}
