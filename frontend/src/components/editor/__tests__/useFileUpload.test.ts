import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { HTTPError } from '@/api/client'
import { uploadAssets } from '@/api/posts'
import { useFileUpload } from '../useFileUpload'

vi.mock('@/api/posts', () => ({
  uploadAssets: vi.fn(),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual('@/api/client')
  return { ...actual }
})

const mockUploadAssets = vi.mocked(uploadAssets)
const httpErrorOptions = {} as ConstructorParameters<typeof HTTPError>[2]

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('triggerUpload is a no-op when filePath is null', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: null }),
    )
    act(() => result.current.triggerUpload())
    expect(result.current.uploading).toBe(false)
  })

  it('inputProps includes accept when provided', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', accept: 'image/*' }),
    )
    expect(result.current.inputProps.accept).toBe('image/*')
  })

  it('inputProps does not include accept when not provided', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md' }),
    )
    expect(result.current.inputProps.accept).toBeUndefined()
  })

  it('inputProps includes multiple based on option', () => {
    const { result: multiResult } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', multiple: true }),
    )
    expect(multiResult.current.inputProps.multiple).toBe(true)

    const { result: singleResult } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', multiple: false }),
    )
    expect(singleResult.current.inputProps.multiple).toBe(false)
  })

  it('calls uploadAssets and onSuccess on successful upload', async () => {
    mockUploadAssets.mockResolvedValue({ uploaded: ['photo.png'] })
    const onSuccess = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onSuccess,
      }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(mockUploadAssets).toHaveBeenCalledWith('posts/test/index.md', [file])
      expect(onSuccess).toHaveBeenCalledWith(['photo.png'])
      expect(result.current.uploading).toBe(false)
    })
  })

  it('calls onError with parsed message on HTTPError', async () => {
    const errorResponse = new Response(JSON.stringify({ detail: 'File too large' }), {
      status: 413,
      statusText: 'Payload Too Large',
    })
    mockUploadAssets.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onError,
      }),
    )

    const file = new File(['content'], 'big.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith('File too large')
    })
    expect(result.current.uploading).toBe(false)
  })

  it('calls onError with generic message on non-HTTP error', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUploadAssets.mockRejectedValue(new Error('Network failure'))
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onError,
      }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith('Failed to upload files')
    })
    expect(result.current.uploading).toBe(false)
    consoleError.mockRestore()
  })

  it('console.error is called on HTTPError when onError is not provided', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const errorResponse = new Response(JSON.stringify({ detail: 'File too large' }), {
      status: 413,
      statusText: 'Payload Too Large',
    })
    mockUploadAssets.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )

    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md' }),
    )

    const file = new File(['content'], 'big.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(consoleError).toHaveBeenCalled()
    })
    consoleError.mockRestore()
  })

  it('console.error is called on non-HTTP error when onError is not provided', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUploadAssets.mockRejectedValue(new TypeError('Network failure'))

    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md' }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(consoleError).toHaveBeenCalled()
    })
    consoleError.mockRestore()
  })

  it('console.error is called on non-HTTP error even when onError IS provided', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const syntaxErr = new SyntaxError('Bad JSON')
    mockUploadAssets.mockRejectedValue(syntaxErr)
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', onError }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith('Failed to upload files')
      expect(consoleError).toHaveBeenCalledWith(syntaxErr)
    })
    consoleError.mockRestore()
  })

  it('calls onStart callback before onSuccess during upload', async () => {
    const callOrder: string[] = []
    mockUploadAssets.mockResolvedValue({ uploaded: ['photo.png'] })
    const onStart = vi.fn(() => { callOrder.push('onStart') })
    const onSuccess = vi.fn(() => { callOrder.push('onSuccess') })

    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', onStart, onSuccess }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(onStart).toHaveBeenCalledTimes(1)
      expect(onSuccess).toHaveBeenCalledWith(['photo.png'])
      expect(callOrder).toEqual(['onStart', 'onSuccess'])
    })
  })

  it('does nothing when no files are selected', () => {
    const onSuccess = vi.fn()
    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onSuccess,
      }),
    )

    act(() => {
      result.current.inputProps.onChange({
        target: { files: [], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    expect(mockUploadAssets).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('inputProps and its onChange are stable when only callbacks change between renders', () => {
    const makeOnSuccess = () => vi.fn()

    const { result, rerender } = renderHook(
      ({ onSuccess }: { onSuccess: (uploaded: string[]) => void }) =>
        useFileUpload({ filePath: 'posts/test/index.md', onSuccess }),
      { initialProps: { onSuccess: makeOnSuccess() } },
    )

    const firstInputProps = result.current.inputProps
    const firstOnChange = firstInputProps.onChange

    rerender({ onSuccess: makeOnSuccess() })

    expect(result.current.inputProps).toBe(firstInputProps)
    expect(result.current.inputProps.onChange).toBe(firstOnChange)
  })

  it('uses the latest onSuccess callback even when handleChange identity is stable', async () => {
    mockUploadAssets.mockResolvedValue({ uploaded: ['photo.png'] })

    const firstOnSuccess = vi.fn()
    const secondOnSuccess = vi.fn()

    const { result, rerender } = renderHook(
      ({ onSuccess }: { onSuccess: (uploaded: string[]) => void }) =>
        useFileUpload({ filePath: 'posts/test/index.md', onSuccess }),
      { initialProps: { onSuccess: firstOnSuccess } },
    )

    // Switch to a new callback before triggering the upload
    rerender({ onSuccess: secondOnSuccess })

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    act(() => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    await waitFor(() => {
      expect(secondOnSuccess).toHaveBeenCalledWith(['photo.png'])
    })
    expect(firstOnSuccess).not.toHaveBeenCalled()
  })
})
