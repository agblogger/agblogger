import { useState, useEffect, useRef, useCallback } from 'react'
import { Paperclip, ChevronDown, ChevronUp, Plus } from 'lucide-react'
import { HTTPError } from '@/api/client'
import type { AssetInfo } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { fetchPostAssets, deletePostAsset, renamePostAsset, uploadAssets } from '@/api/posts'
import FileCard from './FileCard'
import { rewriteMarkdownAssetReferences } from './markdownAssetReferences'

interface FileStripProps {
  filePath: string | null
  body: string
  onBodyChange: (body: string) => void
  onInsertAtCursor: (text: string) => void
  disabled: boolean
}

export default function FileStrip({
  filePath,
  body,
  onBodyChange,
  onInsertAtCursor,
  disabled,
}: FileStripProps) {
  const [expanded, setExpanded] = useState(false)
  const [assets, setAssets] = useState<AssetInfo[]>([])
  const [operating, setOperating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadAssets = useCallback(async () => {
    if (filePath === null) return
    try {
      const response = await fetchPostAssets(filePath)
      setAssets(response.assets)
      setError(null)
    } catch (err) {
      if (err instanceof HTTPError) {
        const detail = await parseErrorDetail(err.response, 'Failed to load assets')
        setError(detail)
      } else {
        setError('Failed to load assets')
      }
    }
  }, [filePath])

  useEffect(() => {
    void loadAssets()
  }, [loadAssets])

  if (filePath === null) {
    return (
      <div className="rounded-lg border border-border px-4 py-3 text-sm text-muted">
        Save to start adding files
      </div>
    )
  }

  const controlsDisabled = disabled || operating

  function handleToggle() {
    setExpanded((prev) => !prev)
  }

  function handleInsert(name: string, isImage: boolean) {
    const markdown = isImage ? `![${name}](${name})` : `[${name}](${name})`
    onInsertAtCursor(markdown)
  }

  function handleDelete(name: string) {
    if (body.includes(name)) {
      setConfirmDelete(name)
    } else {
      void performDelete(name)
    }
  }

  async function performDelete(name: string) {
    if (filePath === null) return
    setOperating(true)
    setError(null)
    setConfirmDelete(null)
    try {
      await deletePostAsset(filePath, name)
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError) {
        const detail = await parseErrorDetail(err.response, 'Failed to delete file')
        setError(detail)
      } else {
        setError('Failed to delete file')
      }
    } finally {
      setOperating(false)
    }
  }

  async function handleRename(oldName: string, newName: string) {
    if (filePath === null) return
    setOperating(true)
    setError(null)
    try {
      await renamePostAsset(filePath, oldName, newName)
      const updatedBody = rewriteMarkdownAssetReferences(body, oldName, newName)
      onBodyChange(updatedBody)
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError) {
        const detail = await parseErrorDetail(err.response, 'Failed to rename file')
        setError(detail)
      } else {
        setError('Failed to rename file')
      }
    } finally {
      setOperating(false)
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    if (filePath === null) return
    const files = e.target.files
    if (files === null || files.length === 0) return
    setOperating(true)
    setError(null)
    try {
      await uploadAssets(filePath, Array.from(files))
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError) {
        const detail = await parseErrorDetail(err.response, 'Failed to upload files')
        setError(detail)
      } else {
        setError('Failed to upload files')
      }
    } finally {
      setOperating(false)
      // Reset input so the same file can be re-uploaded
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const headerLabel = assets.length > 0 ? `Files (${String(assets.length)})` : 'Files'
  const ChevronIcon = expanded ? ChevronUp : ChevronDown

  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center gap-2 px-4 py-2 text-sm font-medium text-ink hover:bg-paper-warm transition-colors rounded-lg"
      >
        <Paperclip size={16} className="text-muted" />
        <span>{headerLabel}</span>
        <ChevronIcon size={16} className="ml-auto text-muted" />
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          {error !== null && (
            <p className="text-sm text-red-600 mb-2">{error}</p>
          )}

          {confirmDelete !== null && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm">
              <p className="text-red-800">
                This file is referenced in your post. Delete anyway?
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmDelete(null)}
                  disabled={controlsDisabled}
                  className="rounded px-3 py-1 text-sm border border-border bg-paper text-ink hover:bg-paper-warm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void performDelete(confirmDelete)}
                  disabled={controlsDisabled}
                  className="rounded px-3 py-1 text-sm bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Delete
                </button>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            {assets.map((asset) => (
              <FileCard
                key={asset.name}
                asset={asset}
                filePath={filePath}
                onInsert={handleInsert}
                onDelete={handleDelete}
                onRename={(oldName, newName) => void handleRename(oldName, newName)}
                disabled={controlsDisabled}
              />
            ))}

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={controlsDisabled}
              className="w-20 h-20 rounded-lg border-2 border-dashed border-border flex items-center justify-center text-muted hover:border-accent hover:text-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Upload file"
            >
              <Plus size={24} />
            </button>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={(e) => void handleUpload(e)}
              className="hidden"
            />
          </div>

          <p className="mt-2 text-xs text-muted">Max 10 MB per file</p>
        </div>
      )}
    </div>
  )
}
