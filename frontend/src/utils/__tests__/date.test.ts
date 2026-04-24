import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  formatLocalDate,
  formatRelativeDate,
  localDateToUtcStart,
  localDateToUtcEnd,
  utcTimestampToLocalDateInput,
} from '../date'

describe('formatLocalDate', () => {
  it('formats a valid ISO timestamp using browser locale', () => {
    const result = formatLocalDate('2026-03-01T12:00:00+00:00')
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('handles backend space-separated timestamps', () => {
    const result = formatLocalDate('2026-03-01 12:00:00+00:00')
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('handles two-digit UTC offset', () => {
    const result = formatLocalDate('2026-03-01T12:00:00+00')
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('supports Intl.DateTimeFormatOptions', () => {
    const result = formatLocalDate('2026-03-01T12:00:00+00:00', { dateStyle: 'long' })
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'long' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('includes time when timeStyle is provided', () => {
    const result = formatLocalDate('2026-03-01T12:00:00+00:00', {
      dateStyle: 'medium',
      timeStyle: 'medium',
    })
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'medium',
    }).format(new Date('2026-03-01T12:00:00+00:00'))
    expect(result).toBe(expected)
  })

  it('falls back to full string on invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatLocalDate('not-a-date')).toBe('not-a-date')
  })

  it('falls back to full string on multi-word invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatLocalDate('totally invalid date')).toBe('totally invalid date')
  })

  it('returns empty string for empty input', () => {
    expect(formatLocalDate('')).toBe('')
  })

  it('handles bare YYYY-MM-DD date strings without a time component', () => {
    // Regression: normalise() used to corrupt bare dates like "2024-01-01" by
    // matching the day part "-01" as a bare UTC offset and producing "2024-01-01:00".
    const result = formatLocalDate('2024-01-01', { month: 'numeric', day: 'numeric' })
    const expected = new Intl.DateTimeFormat(undefined, { month: 'numeric', day: 'numeric' }).format(
      new Date(2024, 0, 1), // local midnight January 1, 2024 — same as parseISO('2024-01-01')
    )
    expect(result).toBe(expected)
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
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('handles backend space-separated timestamps', () => {
    const result = formatRelativeDate('2026-03-09 12:00:00+00:00')
    expect(result).toBe('1 day ago')
  })

  it('handles two-digit offset', () => {
    const result = formatRelativeDate('2026-03-01 12:00:00+00')
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
      new Date('2026-03-01T12:00:00+00:00'),
    )
    expect(result).toBe(expected)
  })

  it('falls back to full string on invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatRelativeDate('not-a-date')).toBe('not-a-date')
  })

  it('falls back to full string on multi-word invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(formatRelativeDate('totally invalid date')).toBe('totally invalid date')
  })
})

describe('localDateToUtcStart', () => {
  it('converts a date string to UTC start-of-day ISO string', () => {
    const result = localDateToUtcStart('2026-03-01')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z$/)
    const parsed = new Date(result)
    expect(parsed.getFullYear()).toBe(2026)
    const local = new Date(2026, 2, 1, 0, 0, 0, 0)
    expect(parsed.getTime()).toBe(local.getTime())
  })

  it('returns empty string for empty input', () => {
    expect(localDateToUtcStart('')).toBe('')
  })
})

describe('localDateToUtcEnd', () => {
  it('converts a date string to UTC end-of-day ISO string', () => {
    const result = localDateToUtcEnd('2026-03-01')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z$/)
    const parsed = new Date(result)
    const local = new Date(2026, 2, 1, 23, 59, 59, 999)
    expect(parsed.getTime()).toBe(local.getTime())
  })

  it('returns empty string for empty input', () => {
    expect(localDateToUtcEnd('')).toBe('')
  })
})

describe('utcTimestampToLocalDateInput', () => {
  it('converts a UTC ISO timestamp into a local date input value', () => {
    const iso = localDateToUtcStart('2026-03-01')
    expect(utcTimestampToLocalDateInput(iso)).toBe('2026-03-01')
  })

  it('returns empty string for empty input', () => {
    expect(utcTimestampToLocalDateInput('')).toBe('')
  })

  it('falls back to the original string on invalid input', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(utcTimestampToLocalDateInput('not-a-date')).toBe('not-a-date')
  })
})
