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

describe('scroll sync position helpers (via hook behaviour)', () => {
  it('scrolling editor with sentinel data moves preview proportionally', () => {
    // Set up a textarea at scrollTop=0, a preview with a sentinel at offsetTop=100 for line 0
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

    // Inject a sentinel element into the preview div
    const sentinel = document.createElement('span')
    sentinel.id = 'agbpos-L0'
    Object.defineProperty(sentinel, 'offsetTop', { get: () => 0, configurable: true })
    preview.appendChild(sentinel)

    const previewScrollSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', {
      get: () => 0,
      set: previewScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Hello world.',
      })
    )

    act(() => result.current.onEditorScroll())
    // With only one sentinel at top=0 and editor at scrollTop=0,
    // preview should be set to 0
    expect(previewScrollSetter).toHaveBeenCalledWith(0)
  })

  it('re-entrancy guard prevents feedback loop', () => {
    const textarea = makeTextarea(100)
    const preview = makeDiv(0)

    const previewScrollSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', {
      get: () => 0,
      set: previewScrollSetter,
      configurable: true,
    })
    const textareaScrollSetter = vi.fn()
    Object.defineProperty(textarea, 'scrollTop', {
      get: () => 100,
      set: textareaScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Paragraph.',
      })
    )

    // Simulate editor scroll triggering preview scroll triggering editor scroll again
    act(() => {
      result.current.onEditorScroll()
      // Immediately call preview scroll (simulating the scroll event it fires)
      result.current.onPreviewScroll()
    })

    // textareaScrollSetter should NOT have been called (re-entrancy guard active)
    expect(textareaScrollSetter).not.toHaveBeenCalled()
    // But preview should have been set once from editor scroll
    expect(previewScrollSetter).toHaveBeenCalledTimes(1)
  })
})
