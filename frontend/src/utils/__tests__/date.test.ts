import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { formatDate, formatRelativeDate } from '../date'

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

describe('formatRelativeDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-03-10T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns relative time for dates less than 7 days ago', () => {
    const result = formatRelativeDate('2026-03-08T12:00:00+00:00')
    expect(result).toBe('2 days ago')
  })

  it('returns absolute date for dates 7+ days ago', () => {
    const result = formatRelativeDate('2026-03-01T12:00:00+00:00')
    expect(result).toBe('Mar 1, 2026')
  })

  it('handles backend space-separated timestamps', () => {
    const result = formatRelativeDate('2026-03-09 12:00:00+00:00')
    expect(result).toBe('1 day ago')
  })

  it('handles two-digit offset', () => {
    const result = formatRelativeDate('2026-03-01 12:00:00+00')
    expect(result).toBe('Mar 1, 2026')
  })

  it('falls back to raw date portion on invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatRelativeDate('not-a-date')).toBe('not-a-date')
  })
})
