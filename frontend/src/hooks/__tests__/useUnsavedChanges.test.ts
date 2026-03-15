import { renderHook, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { createElement, useState } from 'react'
import { createMemoryRouter, RouterProvider, Link, useLocation } from 'react-router-dom'

import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'

/** Wrapper for renderHook — single-route data router so useBlocker works. */
function createWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const router = createMemoryRouter(
      [{ path: '/', element: children }],
      { initialEntries: ['/'] },
    )
    return createElement(RouterProvider, { router })
  }
}

/** Component wrapper for testing blocker behavior via user interaction. */
function TestHost({ isDirty }: { isDirty: boolean }) {
  useUnsavedChanges(isDirty)
  const location = useLocation()
  return createElement(
    'div',
    null,
    createElement('span', { 'data-testid': 'location' }, location.pathname),
    createElement(Link, { to: '/other' }, 'Leave'),
  )
}

function renderWithHost(isDirty: boolean) {
  const router = createMemoryRouter(
    [
      { path: '/', element: createElement(TestHost, { isDirty }) },
      { path: '/other', element: createElement('div', null, 'Other page') },
    ],
    { initialEntries: ['/'] },
  )
  return render(createElement(RouterProvider, { router }))
}

function TestHostWithDirtyControls() {
  const [isDirty, setIsDirty] = useState(true)
  const { markSaved } = useUnsavedChanges(isDirty)
  const location = useLocation()
  return createElement(
    'div',
    null,
    createElement('span', { 'data-testid': 'location' }, location.pathname),
    createElement(
      'button',
      { type: 'button', onClick: () => markSaved() },
      'Mark Saved',
    ),
    createElement(
      'button',
      { type: 'button', onClick: () => setIsDirty(false) },
      'Clean',
    ),
    createElement(
      'button',
      { type: 'button', onClick: () => setIsDirty(true) },
      'Dirty Again',
    ),
    createElement(Link, { to: '/other' }, 'Leave'),
  )
}

function renderWithDirtyControls() {
  const router = createMemoryRouter(
    [
      { path: '/', element: createElement(TestHostWithDirtyControls) },
      { path: '/other', element: createElement('div', null, 'Other page') },
    ],
    { initialEntries: ['/'] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('useUnsavedChanges', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  describe('beforeunload', () => {
    it('registers beforeunload when dirty', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')

      renderHook(() => useUnsavedChanges(true), { wrapper: createWrapper() })

      expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    })

    it('does not register beforeunload when not dirty', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')

      renderHook(() => useUnsavedChanges(false), { wrapper: createWrapper() })

      const beforeunloadCalls = addSpy.mock.calls.filter(([event]) => event === 'beforeunload')
      expect(beforeunloadCalls).toHaveLength(0)
    })

    it('unregisters beforeunload when dirty becomes false', () => {
      const removeSpy = vi.spyOn(window, 'removeEventListener')

      const { rerender } = renderHook(
        ({ dirty }) => useUnsavedChanges(dirty),
        { wrapper: createWrapper(), initialProps: { dirty: true } },
      )

      rerender({ dirty: false })

      expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    })

    it('sets returnValue when beforeunload fires', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')

      renderHook(() => useUnsavedChanges(true), { wrapper: createWrapper() })

      const handler = addSpy.mock.calls.find(([event]) => event === 'beforeunload')?.[1]
      expect(handler).toBeTypeOf('function')
      if (typeof handler !== 'function') {
        throw new Error('beforeunload handler missing')
      }

      const beforeUnloadEvent = {
        preventDefault: vi.fn(),
        returnValue: undefined as string | undefined,
      }

      handler(beforeUnloadEvent as unknown as BeforeUnloadEvent)

      expect(beforeUnloadEvent.preventDefault).toHaveBeenCalledOnce()
      expect(beforeUnloadEvent.returnValue).toBe('')
    })
  })

  describe('navigation blocker', () => {
    it('shows confirm dialog when navigating while dirty', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalledWith(
        'You have unsaved changes. Are you sure you want to leave?',
      )
      // Navigation should be blocked
      expect(screen.getByTestId('location')).toHaveTextContent('/')
    })

    it('allows navigation when user confirms', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('Other page')).toBeInTheDocument()
      })
    })

    it('blocks navigation when user cancels', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalled()
      expect(screen.getByTestId('location')).toHaveTextContent('/')
    })

    it('does not show confirm when not dirty', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm')
      const user = userEvent.setup()
      renderWithHost(false)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).not.toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('Other page')).toBeInTheDocument()
      })
    })
  })

  describe('markSaved', () => {
    it('returns a markSaved function', () => {
      const { result } = renderHook(() => useUnsavedChanges(false), {
        wrapper: createWrapper(),
      })

      expect(result.current.markSaved).toBeInstanceOf(Function)
    })

    it('allows navigation without confirm when markSaved is called before navigating', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm')
      const user = userEvent.setup()

      renderWithDirtyControls()

      await user.click(screen.getByRole('button', { name: 'Mark Saved' }))
      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).not.toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('Other page')).toBeInTheDocument()
      })
    })

    it('markSaved is referentially stable across renders', () => {
      const { result, rerender } = renderHook(
        ({ dirty }) => useUnsavedChanges(dirty),
        { wrapper: createWrapper(), initialProps: { dirty: false } },
      )
      const first = result.current.markSaved
      rerender({ dirty: true })
      expect(result.current.markSaved).toBe(first)
    })

    it('does not bypass prompts after the form becomes dirty again', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()

      renderWithDirtyControls()

      await user.click(screen.getByRole('button', { name: 'Mark Saved' }))
      await user.click(screen.getByRole('button', { name: 'Clean' }))
      await user.click(screen.getByRole('button', { name: 'Dirty Again' }))
      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalledWith(
        'You have unsaved changes. Are you sure you want to leave?',
      )
      expect(screen.getByTestId('location')).toHaveTextContent('/')
    })
  })
})
