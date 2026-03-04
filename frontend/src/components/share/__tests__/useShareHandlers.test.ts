import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import * as shareUtils from '../shareUtils'
import { useShareHandlers } from '../useShareHandlers'

import { storage } from './testUtils'

vi.mock('../shareUtils', async () => {
  const actual = await vi.importActual<typeof import('../shareUtils')>('../shareUtils')
  return { ...actual }
})

describe('useShareHandlers', () => {
  const title = 'Hello World'
  const author: string | null = 'Alice'
  const url = 'https://blog.example.com/post/hello'

  beforeEach(() => {
    storage.clear()
    vi.restoreAllMocks()
  })

  describe('shareText generation', () => {
    it('generates share text with author', () => {
      const { result } = renderHook(() => useShareHandlers(title, author, url))
      expect(result.current.shareText).toBe(
        '\u201cHello World\u201d by Alice https://blog.example.com/post/hello',
      )
    })

    it('generates share text without author', () => {
      const { result } = renderHook(() => useShareHandlers(title, null, url))
      expect(result.current.shareText).toBe(
        '\u201cHello World\u201d https://blog.example.com/post/hello',
      )
    })
  })

  describe('handlePlatformClick', () => {
    it('opens window for mastodon with valid instance', () => {
      storage.set('agblogger:mastodon-instance', 'hachyderm.io')
      const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      act(() => {
        result.current.handlePlatformClick('mastodon')
      })

      expect(windowOpen).toHaveBeenCalledWith(
        expect.stringContaining('https://hachyderm.io/share?text='),
        '_blank',
        'noopener,noreferrer',
      )
      windowOpen.mockRestore()
    })

    it('shows mastodon prompt when no instance is saved', () => {
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      act(() => {
        result.current.handlePlatformClick('mastodon')
      })

      expect(result.current.showMastodonPrompt).toBe(true)
    })

    it('opens window for non-mastodon platforms', () => {
      const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      act(() => {
        result.current.handlePlatformClick('bluesky')
      })

      expect(windowOpen).toHaveBeenCalledWith(
        expect.stringContaining('https://bsky.app/intent/compose?text='),
        '_blank',
        'noopener,noreferrer',
      )
      windowOpen.mockRestore()
    })
  })

  describe('handleCopy', () => {
    it('sets copied=true on success', async () => {
      vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(true)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      await act(async () => {
        await result.current.handleCopy()
      })

      expect(result.current.copied).toBe(true)
      expect(result.current.copyFailed).toBe(false)
    })

    it('sets copyFailed=true on failure', async () => {
      vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(false)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      await act(async () => {
        await result.current.handleCopy()
      })

      expect(result.current.copyFailed).toBe(true)
      expect(result.current.copied).toBe(false)
    })
  })

  describe('handleNativeShare', () => {
    it('swallows AbortError', async () => {
      const abortError = new DOMException('Share cancelled', 'AbortError')
      vi.spyOn(shareUtils, 'nativeShare').mockRejectedValue(abortError)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      // Should not throw
      await act(async () => {
        await result.current.handleNativeShare()
      })
    })

    it('re-throws non-AbortError', async () => {
      const typeError = new TypeError('Invalid share data')
      vi.spyOn(shareUtils, 'nativeShare').mockRejectedValue(typeError)
      const { result } = renderHook(() => useShareHandlers(title, author, url))

      await expect(
        act(async () => {
          await result.current.handleNativeShare()
        }),
      ).rejects.toThrow('Invalid share data')
    })
  })

  describe('onAction callback', () => {
    it('calls onAction after successful platform click', () => {
      vi.spyOn(window, 'open').mockReturnValue(null)
      const onAction = vi.fn()
      const { result } = renderHook(() => useShareHandlers(title, author, url, onAction))

      act(() => {
        result.current.handlePlatformClick('bluesky')
      })

      expect(onAction).toHaveBeenCalledOnce()
    })

    it('calls onAction after successful copy', async () => {
      vi.useFakeTimers()
      vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(true)
      const onAction = vi.fn()
      const { result } = renderHook(() => useShareHandlers(title, author, url, onAction))

      await act(async () => {
        await result.current.handleCopy()
      })

      act(() => {
        vi.advanceTimersByTime(3000)
      })

      expect(onAction).toHaveBeenCalledOnce()
      vi.useRealTimers()
    })

    it('calls onAction after email click', () => {
      const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
      const onAction = vi.fn()
      const { result } = renderHook(() => useShareHandlers(title, author, url, onAction))

      act(() => {
        result.current.handleEmailClick()
      })

      expect(onAction).toHaveBeenCalledOnce()
      windowOpen.mockRestore()
    })

    it('does not call onAction when mastodon has no instance', () => {
      const onAction = vi.fn()
      const { result } = renderHook(() => useShareHandlers(title, author, url, onAction))

      act(() => {
        result.current.handlePlatformClick('mastodon')
      })

      expect(onAction).not.toHaveBeenCalled()
    })
  })
})
