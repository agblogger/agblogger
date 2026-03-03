import { describe, expect, it, vi } from 'vitest'

import { formatDate } from '../date'

describe('formatDate', () => {
  it('formats standard ISO timestamp', () => {
    expect(formatDate('2026-03-01T12:00:00+00:00')).toBe('Mar 1, 2026')
  })

  it('handles space-separated backend timestamps', () => {
    expect(formatDate('2026-03-01 12:00:00+00:00')).toBe('Mar 1, 2026')
  })

  it('handles two-digit UTC offset', () => {
    expect(formatDate('2026-03-01T12:00:00+00')).toBe('Mar 1, 2026')
  })

  it('handles negative UTC offset', () => {
    expect(formatDate('2026-03-01T12:00:00-05')).toBe('Mar 1, 2026')
  })

  it('handles space-separated with two-digit offset', () => {
    expect(formatDate('2026-03-01 12:00:00+00')).toBe('Mar 1, 2026')
  })

  it('falls back to raw date portion on invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('supports custom patterns', () => {
    expect(formatDate('2026-03-01T12:00:00+00:00', 'yyyy-MM-dd')).toBe('2026-03-01')
  })

  it('returns empty string for completely empty input fallback', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatDate('')).toBe('')
  })
})
