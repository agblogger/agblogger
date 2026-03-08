import { useState, useRef, useEffect, useCallback } from 'react'
import { File, MoreVertical } from 'lucide-react'
import type { AssetInfo } from '@/api/client'

interface FileCardProps {
  asset: AssetInfo
  filePath: string
  onInsert: (name: string, isImage: boolean) => void
  onDelete: (name: string) => void
  onRename: (oldName: string, newName: string) => void
  disabled: boolean
}

function getAssetDir(filePath: string): string {
  const segments = filePath.split('/')
  segments.pop()
  return segments.join('/')
}

export default function FileCard({
  asset,
  filePath,
  onInsert,
  onDelete,
  onRename,
  disabled,
}: FileCardProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(asset.name)
  const menuRef = useRef<HTMLDivElement>(null)
  const renameRef = useRef<HTMLInputElement>(null)

  const dir = getAssetDir(filePath)
  const thumbnailSrc = `/api/content/${dir}/${asset.name}`

  const closeMenu = useCallback(() => {
    setMenuOpen(false)
  }, [])

  useEffect(() => {
    if (!menuOpen) return

    function handleMouseDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu()
      }
    }

    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [menuOpen, closeMenu])

  useEffect(() => {
    if (renaming && renameRef.current) {
      renameRef.current.focus()
      renameRef.current.select()
    }
  }, [renaming])

  function handleInsert() {
    onInsert(asset.name, asset.is_image)
    closeMenu()
  }

  function handleCopyName() {
    void navigator.clipboard.writeText(asset.name).catch(() => undefined)
    closeMenu()
  }

  function handleRenameStart() {
    setRenameValue(asset.name)
    setRenaming(true)
    closeMenu()
  }

  function handleDelete() {
    onDelete(asset.name)
    closeMenu()
  }

  function handleRenameConfirm() {
    const trimmed = renameValue.trim()
    if (trimmed !== '' && trimmed !== asset.name) {
      onRename(asset.name, trimmed)
    }
    setRenaming(false)
  }

  function handleRenameCancel() {
    setRenaming(false)
  }

  function handleRenameKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleRenameConfirm()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      handleRenameCancel()
    }
  }

  return (
    <div className="relative w-20 flex-shrink-0">
      <div className="w-20 h-20 rounded-lg border border-border bg-paper-warm flex items-center justify-center overflow-hidden">
        {asset.is_image ? (
          <img
            src={thumbnailSrc}
            alt={asset.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <File size={28} className="text-muted" />
        )}
      </div>

      <div className="absolute top-0.5 right-0.5" ref={menuRef}>
        <button
          type="button"
          aria-label="menu"
          disabled={disabled}
          onClick={() => setMenuOpen((prev) => !prev)}
          className="p-0.5 rounded bg-paper/80 text-muted hover:text-ink transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <MoreVertical size={14} />
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 z-50 min-w-[120px] rounded-lg border border-border bg-paper shadow-lg py-1">
            <button
              type="button"
              onClick={handleInsert}
              className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
            >
              Insert
            </button>
            <button
              type="button"
              onClick={handleCopyName}
              className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
            >
              Copy name
            </button>
            <button
              type="button"
              onClick={handleRenameStart}
              className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
            >
              Rename
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {renaming ? (
        <input
          ref={renameRef}
          type="text"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={handleRenameKeyDown}
          onBlur={handleRenameConfirm}
          className="mt-1 w-full text-xs text-ink bg-paper border border-border rounded px-1 py-0.5 truncate"
        />
      ) : (
        <p className="mt-1 text-xs text-muted truncate" title={asset.name}>
          {asset.name}
        </p>
      )}
    </div>
  )
}
