import { useEffect, useRef, useState } from 'react'
import { Check, Link, Mail, Share2, X as XIcon } from 'lucide-react'

import ShareDropdownContent from './ShareDropdownContent'
import type { ShareProps } from './shareTypes'
import { useShareHandlers } from './useShareHandlers'

export default function ShareBar({ title, author, url }: ShareProps) {
  const [showDropdown, setShowDropdown] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const { copied, copyFailed, handleEmailClick, handleCopy } = useShareHandlers(
    title,
    author,
    url,
  )

  useEffect(() => {
    if (!showDropdown) return
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current !== null && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showDropdown])

  return (
    <div className="mt-10 border-t border-border pt-6">
      <div className="flex flex-wrap items-center gap-1">
        <div className="relative" ref={dropdownRef}>
          <div className="tooltip-wrap">
            <button
              onClick={() => setShowDropdown((prev) => !prev)}
              aria-label="Share this post"
              className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
            >
              <Share2 size={18} />
            </button>
            <span role="tooltip">Share</span>
          </div>

          {showDropdown && (
            <div className="animate-fade-in absolute bottom-full left-0 z-40 mb-2 min-w-[200px] rounded-xl border border-border bg-paper p-2 shadow-lg">
              <ShareDropdownContent
                title={title}
                author={author}
                url={url}
                onClose={() => setShowDropdown(false)}
              />
            </div>
          )}
        </div>

        <div className="tooltip-wrap">
          <button
            onClick={handleEmailClick}
            aria-label="Share via email"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
          >
            <Mail size={18} />
          </button>
          <span role="tooltip">Share via email</span>
        </div>

        <div className="tooltip-wrap">
          <button
            onClick={() => void handleCopy()}
            aria-label="Copy link"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
          >
            {copied ? (
              <Check size={18} className="text-green-600 dark:text-green-400" />
            ) : copyFailed ? (
              <XIcon size={18} className="text-red-600 dark:text-red-400" />
            ) : (
              <Link size={18} />
            )}
          </button>
          <span role="tooltip">Copy link</span>
        </div>

        {copied && (
          <span className="animate-fade-in text-xs font-medium text-green-600 dark:text-green-400">
            Copied!
          </span>
        )}
        {copyFailed && (
          <span className="animate-fade-in text-xs font-medium text-red-600 dark:text-red-400">
            Copy failed
          </span>
        )}
      </div>
    </div>
  )
}
