import { useCallback, useMemo, useRef, useState } from 'react'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { uploadAssets } from '@/api/posts'

interface UseFileUploadOptions {
  filePath: string | null
  accept?: string
  multiple?: boolean
  onStart?: () => void
  onSuccess?: (uploaded: string[]) => void
  onError?: (message: string) => void
}

export function useFileUpload({
  filePath,
  accept,
  multiple = true,
  onStart,
  onSuccess,
  onError,
}: UseFileUploadOptions) {
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Store the latest callbacks in refs so handleChange can stay stable
  // without capturing stale closures.
  const onStartRef = useRef(onStart)
  const onSuccessRef = useRef(onSuccess)
  const onErrorRef = useRef(onError)
  onStartRef.current = onStart
  onSuccessRef.current = onSuccess
  onErrorRef.current = onError

  const triggerUpload = useCallback(() => {
    if (filePath === null) return
    inputRef.current?.click()
  }, [filePath])

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      if (filePath === null) return
      const files = e.target.files
      if (files === null || files.length === 0) return

      setUploading(true)
      onStartRef.current?.()
      try {
        const result = await uploadAssets(filePath, Array.from(files))
        onSuccessRef.current?.(result.uploaded)
      } catch (err) {
        if (err instanceof HTTPError) {
          const detail = await parseErrorDetail(err.response, 'Failed to upload files')
          if (onErrorRef.current) {
            onErrorRef.current(detail)
          } else {
            console.error(err)
          }
        } else {
          console.error(err)
          onErrorRef.current?.('Failed to upload files')
        }
      } finally {
        setUploading(false)
        if (inputRef.current) {
          inputRef.current.value = ''
        }
      }
    },
    [filePath],
  )

  const inputProps = useMemo(
    () => ({
      ref: inputRef,
      type: 'file' as const,
      accept,
      multiple,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => void handleChange(e),
      className: 'hidden',
    }),
    [accept, multiple, handleChange],
  )

  return { triggerUpload, uploading, inputProps }
}
