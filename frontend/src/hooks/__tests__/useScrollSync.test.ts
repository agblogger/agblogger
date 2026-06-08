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
  it('exposes syncEditorToPreview and syncPreviewToEditor functions', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(typeof result.current.syncEditorToPreview).toBe('function')
    expect(typeof result.current.syncPreviewToEditor).toBe('function')
  })

  it('syncEditorToPreview is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.syncEditorToPreview()).not.toThrow()
  })

  it('syncPreviewToEditor is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.syncPreviewToEditor()).not.toThrow()
  })
})

describe('sync position helpers (via hook behaviour)', () => {
  it('syncEditorToPreview sets preview.scrollTop based on editor position', () => {
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

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

    act(() => result.current.syncEditorToPreview())
    expect(previewScrollSetter).toHaveBeenCalledWith(0)
  })

  it('syncPreviewToEditor sets textarea.scrollTop based on preview position', () => {
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

    const sentinel = document.createElement('span')
    sentinel.id = 'agbpos-L0'
    Object.defineProperty(sentinel, 'offsetTop', { get: () => 0, configurable: true })
    preview.appendChild(sentinel)

    const textareaScrollSetter = vi.fn()
    Object.defineProperty(textarea, 'scrollTop', {
      get: () => 0,
      set: textareaScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Hello world.',
      })
    )

    act(() => result.current.syncPreviewToEditor())
    expect(textareaScrollSetter).toHaveBeenCalledWith(0)
  })
})
