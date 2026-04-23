import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { AdminSiteSettings, AdminPagesResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockSettings: AdminSiteSettings = {
  title: 'Test Blog',
  description: 'A test blog',
  timezone: 'UTC',
  password_change_disabled: false,
  favicon: null,
}

const mockPages: AdminPagesResponse = {
  pages: [
    { id: 'about', title: 'About', file: 'about.md', is_builtin: false, content: null },
  ],
}

vi.mock('@/api/admin', () => ({
  fetchAdminSiteSettings: vi.fn(),
  fetchAdminPages: vi.fn(),
}))

import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import { useAdminSiteSettings, useAdminPages } from '../useAdminData'

const mockFetchAdminSiteSettings = vi.mocked(fetchAdminSiteSettings)
const mockFetchAdminPages = vi.mocked(fetchAdminPages)

function wrapper({ children }: { children: ReactNode }) {
  return createElement(SWRTestWrapper, null, children)
}

describe('useAdminSiteSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data on success', async () => {
    mockFetchAdminSiteSettings.mockResolvedValueOnce(mockSettings)
    const { result } = renderHook(() => useAdminSiteSettings(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockSettings)
    expect(result.current.error).toBeUndefined()
  })

  it('returns error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchAdminSiteSettings.mockRejectedValueOnce(err)
    const { result } = renderHook(() => useAdminSiteSettings(), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
  })
})

describe('useAdminPages', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data on success', async () => {
    mockFetchAdminPages.mockResolvedValueOnce(mockPages)
    const { result } = renderHook(() => useAdminPages(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockPages)
    expect(result.current.error).toBeUndefined()
  })

  it('returns error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchAdminPages.mockRejectedValueOnce(err)
    const { result } = renderHook(() => useAdminPages(), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
  })
})
