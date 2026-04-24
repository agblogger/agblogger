import { format, formatDistanceToNow, parseISO, isValid, differenceInDays } from 'date-fns'

/**
 * Normalise a backend ISO timestamp (space-separated, two-digit offset)
 * into a standard ISO string suitable for `parseISO`.
 *
 * The offset fix (`+00` → `+00:00`) must only apply when a time component is
 * present. Without this guard the regex matches the day part of a bare
 * `YYYY-MM-DD` string (e.g. `-01`) and corrupts it into `2024-01-01:00`.
 */
function normalise(dateStr: string): string {
  const withT = dateStr.replace(' ', 'T')
  // Only fix a bare two-digit UTC offset when a time component is present
  // (i.e. the string contains 'T' after the date-time delimiter replacement).
  if (!withT.includes('T')) return withT
  return withT.replace(/([+-])(\d{2})$/, '$1$2:00')
}

/**
 * Parse a backend ISO timestamp and format it for display.
 *
 * The backend emits timestamps with a space instead of 'T' and may
 * use a bare two-digit UTC offset (e.g. "+00" instead of "+00:00").
 * This helper normalises both quirks before parsing.
 */
export function formatLocalDate(
  dateStr: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' },
): string {
  if (!dateStr) return ''
  const date = parseISO(normalise(dateStr))
  if (!isValid(date)) {
    console.warn(`Failed to parse date "${dateStr}" (normalised: "${normalise(dateStr)}")`)
    return dateStr
  }
  try {
    return new Intl.DateTimeFormat(undefined, options).format(date)
  } catch (err) {
    console.warn(`Failed to format date "${dateStr}" with options ${JSON.stringify(options)}:`, err)
    return dateStr
  }
}

export function formatDate(dateStr: string, pattern = 'MMM d, yyyy'): string {
  if (!dateStr) return ''
  try {
    return format(parseISO(normalise(dateStr)), pattern)
  } catch (err) {
    console.warn(`Failed to parse date "${dateStr}":`, err)
    return dateStr
  }
}

/**
 * Format a date string as relative ("3 days ago") when recent (< 7 days),
 * otherwise fall back to "MMM d, yyyy".
 */
export function formatRelativeDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const date = parseISO(normalise(dateStr))
    if (Math.abs(differenceInDays(new Date(), date)) < 7) {
      return formatDistanceToNow(date, { addSuffix: true })
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
  } catch (err) {
    console.warn(`Failed to parse date "${dateStr}":`, err)
    return dateStr
  }
}

/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the start of that day in the user's local timezone.
 */
export function localDateToUtcStart(dateStr: string): string {
  if (!dateStr) return ''
  const local = new Date(`${dateStr}T00:00:00`)
  return local.toISOString()
}

/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the end of that day in the user's local timezone.
 */
export function localDateToUtcEnd(dateStr: string): string {
  if (!dateStr) return ''
  const local = new Date(`${dateStr}T23:59:59.999`)
  return local.toISOString()
}

/**
 * Convert a UTC/ISO timestamp from the URL back into a local YYYY-MM-DD
 * value suitable for date input controls.
 */
export function utcTimestampToLocalDateInput(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return format(parseISO(normalise(dateStr)), 'yyyy-MM-dd')
  } catch (err) {
    console.warn(`Failed to parse date "${dateStr}":`, err)
    return dateStr || ''
  }
}
