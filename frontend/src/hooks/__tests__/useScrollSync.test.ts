import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useScrollSync } from '@/hooks/useScrollSync'

function makeTextarea(scrollTop = 0, scrollHeight = 1000, clientHeight = 400): HTMLTextAreaElement {
  const el = document.createElement('textarea')
  Object.defineProperty(el, 'scrollTop', { get: () => scrollTop, set: vi.fn(), configurable: true })
  Object.defineProperty(el, 'scrollHeight', { get: () => scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { get: () => clientHeight, configurable: true })
  Object.defineProperty(el, 'clientWidth', { get: () => 600, configurable: true })
  return el
}

function makeDiv(scrollTop = 0, scrollHeight = 2000, clientHeight = 400): HTMLDivElement {
  const el = document.createElement('div')
  Object.defineProperty(el, 'scrollTop', { get: () => scrollTop, set: vi.fn(), configurable: true })
  Object.defineProperty(el, 'scrollHeight', { get: () => scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { get: () => clientHeight, configurable: true })
  return el
}

describe('useScrollSync', () => {
  it('starts with sync enabled', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(result.current.syncEnabled).toBe(true)
  })

  it('toggleSync toggles syncEnabled', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    act(() => result.current.toggleSync())
    expect(result.current.syncEnabled).toBe(false)
    act(() => result.current.toggleSync())
    expect(result.current.syncEnabled).toBe(true)
  })

  it('onEditorScroll is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    // Should not throw
    expect(() => result.current.onEditorScroll()).not.toThrow()
  })

  it('onPreviewScroll is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.onPreviewScroll()).not.toThrow()
  })

  it('scroll handlers are no-ops when syncEnabled is false', () => {
    const textarea = makeTextarea()
    const preview = makeDiv()
    const previewScrollTopSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', { get: () => 0, set: previewScrollTopSetter, configurable: true })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Some content',
      })
    )
    act(() => result.current.toggleSync())  // disable sync
    act(() => result.current.onEditorScroll())
    expect(previewScrollTopSetter).not.toHaveBeenCalled()
  })
})
