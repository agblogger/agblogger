import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactNode } from 'react'
import { createElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'

import { useEditorAutoSave, DRAFT_SCHEMA_VERSION } from '@/hooks/useEditorAutoSave'
import type { DraftData } from '@/hooks/useEditorAutoSave'

// Mock localStorage since jsdom doesn't always provide it
const storage = new Map<string, string>()
const mockLocalStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
  clear: () => storage.clear(),
  get length() {
    return storage.size
  },
  key: (index: number) => [...storage.keys()][index] ?? null,
}

Object.defineProperty(window, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
})

/** Creates a wrapper with a data router so useBlocker works. */
function createWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const router = createMemoryRouter(
      [{ path: '/', element: children }],
      { initialEntries: ['/'] },
    )
    return createElement(RouterProvider, { router })
  }
}

const baseState: DraftData = {
  title: 'Hello',
  subtitle: '',
  body: '# Hello\n\nWorld',
  labels: ['swe'],
  isDraft: false,
}

describe('useEditorAutoSave', () => {
  beforeEach(() => {
    storage.clear()
  })

  describe('dirty tracking', () => {
    it('is not dirty when state matches initial', () => {
      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )
      expect(result.current.isDirty).toBe(false)
    })

    it('is dirty when body changes', () => {
      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )
      expect(result.current.isDirty).toBe(false)

      rerender({ state: { ...baseState, body: '# Changed' } })
      expect(result.current.isDirty).toBe(true)
    })

    it('is dirty when labels change', () => {
      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      rerender({ state: { ...baseState, labels: ['swe', 'cs'] } })
      expect(result.current.isDirty).toBe(true)
    })

    it('is dirty when isDraft changes', () => {
      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      rerender({ state: { ...baseState, isDraft: true } })
      expect(result.current.isDirty).toBe(true)
    })

    it('is dirty when title changes', () => {
      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      rerender({ state: { ...baseState, title: 'Changed Title' } })
      expect(result.current.isDirty).toBe(true)
    })

  })

  describe('auto-save', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('auto-saves to localStorage after debounce', () => {
      const onRestore = vi.fn()
      const changedState: DraftData = { ...baseState, body: '# Changed' }

      const { rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      // Change state to make it dirty
      rerender({ state: changedState })

      // Not saved yet (debounce)
      expect(localStorage.getItem('test-key')).toBeNull()

      // Advance past debounce
      act(() => {
        vi.advanceTimersByTime(3000)
      })

      const saved = JSON.parse(localStorage.getItem('test-key')!) as DraftData
      expect(saved.body).toBe('# Changed')
      expect(saved.labels).toEqual(['swe'])
      expect(saved.savedAt).toBeDefined()
    })
  })

  describe('draft recovery', () => {
    it('detects existing draft on mount', () => {
      const draft: DraftData = {
        ...baseState,
        body: '# Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(true)
      expect(result.current.draftSavedAt).toBe('2026-02-20T10:00:00.000Z')
    })

    it('restoreDraft calls onRestore and clears draftAvailable', () => {
      const draft: DraftData = {
        ...baseState,
        body: '# Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(true)

      act(() => {
        result.current.restoreDraft()
      })

      expect(onRestore).toHaveBeenCalledWith(draft)
      expect(result.current.draftAvailable).toBe(false)
    })

    it('discardDraft removes localStorage entry', () => {
      const draft: DraftData = {
        ...baseState,
        body: '# Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(true)

      act(() => {
        result.current.discardDraft()
      })

      expect(result.current.draftAvailable).toBe(false)
      expect(localStorage.getItem('test-key')).toBeNull()
    })

    it('reloads draft metadata when key changes', async () => {
      const oldDraft: DraftData = {
        ...baseState,
        body: '# Old Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      const newDraft: DraftData = {
        ...baseState,
        body: '# New Draft',
        savedAt: '2026-02-20T11:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      localStorage.setItem('draft-1', JSON.stringify(oldDraft))
      localStorage.setItem('draft-2', JSON.stringify(newDraft))

      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ key }) => useEditorAutoSave({ key, currentState: baseState, onRestore }),
        { wrapper: createWrapper(), initialProps: { key: 'draft-1' } },
      )

      expect(result.current.draftAvailable).toBe(true)
      expect(result.current.draftSavedAt).toBe('2026-02-20T10:00:00.000Z')

      rerender({ key: 'draft-2' })

      await waitFor(() => {
        expect(result.current.draftAvailable).toBe(true)
        expect(result.current.draftSavedAt).toBe('2026-02-20T11:00:00.000Z')
      })

      act(() => {
        result.current.restoreDraft()
      })
      expect(onRestore).toHaveBeenCalledWith(newDraft)
    })
  })

  describe('markSaved', () => {
    it('clears localStorage and resets dirty', () => {
      vi.useFakeTimers()
      const onRestore = vi.fn()
      const changedState: DraftData = { ...baseState, body: '# Changed' }

      const { result, rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      // Make dirty
      rerender({ state: changedState })
      expect(result.current.isDirty).toBe(true)

      // Let auto-save fire
      act(() => {
        vi.advanceTimersByTime(3000)
      })
      expect(localStorage.getItem('test-key')).not.toBeNull()

      // Mark saved
      act(() => {
        result.current.markSaved()
      })

      expect(result.current.isDirty).toBe(false)
      expect(localStorage.getItem('test-key')).toBeNull()

      vi.useRealTimers()
    })
  })

  describe('enabled parameter', () => {
    it('is not dirty when enabled is false even if state changes', () => {
      const onRestore = vi.fn()
      const { result, rerender } = renderHook(
        ({ state, enabled }) =>
          useEditorAutoSave({ key: 'test-key', currentState: state, onRestore, enabled }),
        { wrapper: createWrapper(), initialProps: { state: baseState, enabled: false } },
      )

      rerender({ state: { ...baseState, body: '# Changed' }, enabled: false })
      expect(result.current.isDirty).toBe(false)
    })

    it('captures baseline when transitioning from disabled to enabled', () => {
      const onRestore = vi.fn()
      const changedState: DraftData = { ...baseState, body: '# Loaded content' }
      const { result, rerender } = renderHook(
        ({ state, enabled }) =>
          useEditorAutoSave({ key: 'test-key', currentState: state, onRestore, enabled }),
        { wrapper: createWrapper(), initialProps: { state: baseState, enabled: false } },
      )

      // Change state while disabled
      rerender({ state: changedState, enabled: false })
      expect(result.current.isDirty).toBe(false)

      // Enable — should capture changedState as baseline
      rerender({ state: changedState, enabled: true })
      expect(result.current.isDirty).toBe(false)

      // Now change from the new baseline — should be dirty
      rerender({ state: { ...changedState, body: '# Different' }, enabled: true })
      expect(result.current.isDirty).toBe(true)
    })
  })

  describe('schema versioning', () => {
    it('ignores drafts with wrong schema version', () => {
      const draft = {
        ...baseState,
        body: '# Old Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: 0, // wrong version
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(false)
    })

    it('ignores drafts without schema version', () => {
      // Legacy draft with no _v field
      const draft = {
        title: 'Legacy',
        body: '# Legacy',
        labels: ['swe'],
        isDraft: false,
        savedAt: '2026-02-20T10:00:00.000Z',
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(false)
    })

    it('loads drafts with correct schema version', () => {
      const draft = {
        ...baseState,
        body: '# Versioned Draft',
        savedAt: '2026-02-20T10:00:00.000Z',
        _v: DRAFT_SCHEMA_VERSION,
      }
      localStorage.setItem('test-key', JSON.stringify(draft))

      const onRestore = vi.fn()
      const { result } = renderHook(
        () => useEditorAutoSave({ key: 'test-key', currentState: baseState, onRestore }),
        { wrapper: createWrapper() },
      )

      expect(result.current.draftAvailable).toBe(true)
      expect(result.current.draftSavedAt).toBe('2026-02-20T10:00:00.000Z')
    })

    it('auto-saved drafts include schema version', () => {
      vi.useFakeTimers()
      const onRestore = vi.fn()
      const changedState: DraftData = { ...baseState, body: '# Changed' }

      const { rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      rerender({ state: changedState })

      act(() => {
        vi.advanceTimersByTime(3000)
      })

      const saved = JSON.parse(localStorage.getItem('test-key')!) as Record<string, unknown>
      expect(saved['_v']).toBe(DRAFT_SCHEMA_VERSION)

      vi.useRealTimers()
    })
  })

  describe('beforeunload', () => {
    it('registers beforeunload when dirty', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')
      const onRestore = vi.fn()

      const { rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      rerender({ state: { ...baseState, body: '# Changed' } })

      expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
      addSpy.mockRestore()
    })

    it('unregisters beforeunload when no longer dirty', () => {
      const removeSpy = vi.spyOn(window, 'removeEventListener')
      const onRestore = vi.fn()

      const { rerender } = renderHook(
        ({ state }) => useEditorAutoSave({ key: 'test-key', currentState: state, onRestore }),
        { wrapper: createWrapper(), initialProps: { state: baseState } },
      )

      // Make dirty
      rerender({ state: { ...baseState, body: '# Changed' } })
      // Make clean again
      rerender({ state: baseState })

      expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
      removeSpy.mockRestore()
    })
  })
})
