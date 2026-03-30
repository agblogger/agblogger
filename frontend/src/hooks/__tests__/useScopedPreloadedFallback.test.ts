import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useScopedPreloadedFallback } from '@/hooks/useScopedPreloadedFallback'

describe('useScopedPreloadedFallback', () => {
  it('returns fallback data when key matches', () => {
    const fallbackData = { id: 1, title: 'My Post' }
    const readFallback = vi.fn(() => fallbackData)

    const { result } = renderHook(() =>
      useScopedPreloadedFallback('post/my-post', readFallback),
    )

    expect(result.current).toEqual(fallbackData)
  })

  it('returns null when readFallback returns null (no preload present)', () => {
    const readFallback = vi.fn(() => null)

    const { result } = renderHook(() =>
      useScopedPreloadedFallback('post/my-post', readFallback),
    )

    expect(result.current).toBeNull()
  })

  it('returns null when key is null (disabled SWR key)', () => {
    const fallbackData = { id: 1, title: 'My Post' }
    const readFallback = vi.fn(() => fallbackData)

    const { result } = renderHook(() =>
      useScopedPreloadedFallback(null, readFallback),
    )

    expect(result.current).toBeNull()
  })

  it('calls readFallback exactly once (lazy initializer behavior)', () => {
    const fallbackData = { id: 1, title: 'My Post' }
    const readFallback = vi.fn(() => fallbackData)

    const { rerender } = renderHook(() =>
      useScopedPreloadedFallback('post/my-post', readFallback),
    )

    rerender()
    rerender()
    rerender()

    expect(readFallback).toHaveBeenCalledTimes(1)
  })

  it('returns null after key changes (stale preload discard)', () => {
    const fallbackData = { id: 1, title: 'My Post' }
    const readFallback = vi.fn(() => fallbackData)

    // Use a mutable key ref to test key changes
    let key: string = 'post/my-post'
    const { result, rerender } = renderHook(() =>
      useScopedPreloadedFallback(key, readFallback),
    )

    // Initially returns data for the matching key
    expect(result.current).toEqual(fallbackData)

    // Change key — preloaded data was for a different key, so returns null
    act(() => {
      key = 'post/other-post'
    })
    rerender()

    expect(result.current).toBeNull()
  })

  it('serializes array keys correctly — [\'post\', \'slug-1\'] should match', () => {
    const fallbackData = { id: 2, title: 'Slug Post' }
    const readFallback = vi.fn(() => fallbackData)
    const key = ['post', 'slug-1'] as const

    const { result } = renderHook(() =>
      useScopedPreloadedFallback(key, readFallback),
    )

    expect(result.current).toEqual(fallbackData)
  })

  it('returns null when array key changes to a different array', () => {
    const fallbackData = { id: 2, title: 'Slug Post' }
    const readFallback = vi.fn(() => fallbackData)

    let key: readonly string[] = ['post', 'slug-1']
    const { result, rerender } = renderHook(() =>
      useScopedPreloadedFallback(key, readFallback),
    )

    expect(result.current).toEqual(fallbackData)

    act(() => {
      key = ['post', 'other-slug']
    })
    rerender()

    expect(result.current).toBeNull()
  })
})
