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
  const normalised = normalise(dateStr)
  const date = parseISO(normalised)
  if (!isValid(date)) {
    console.error(`Failed to parse date "${dateStr}" (normalised: "${normalised}")`)
    return '[invalid date]'
  }
  try {
    return new Intl.DateTimeFormat(undefined, options).format(date)
  } catch (err) {
    console.error(`Failed to format date "${dateStr}" with options ${JSON.stringify(options)}:`, err)
    return '[invalid date]'
  }
}

/**
 * Format a date string as relative ("3 days ago") when recent (< 7 days),
 * otherwise fall back to "MMM d, yyyy".
 */
export function formatRelativeDate(dateStr: string): string {
  if (!dateStr) return ''
  const date = parseISO(normalise(dateStr))
  if (!isValid(date)) {
    console.error(`Failed to parse date "${dateStr}" for relative formatting`)
    return '[invalid date]'
  }
  try {
    if (Math.abs(differenceInDays(new Date(), date)) < 7) {
      return formatDistanceToNow(date, { addSuffix: true })
    }
    return formatLocalDate(dateStr)
  } catch (err) {
    console.error(`Failed to format relative date "${dateStr}":`, err)
    return '[invalid date]'
  }
}

/** Format a Date object as YYYY-MM-DD in the browser's local timezone (not UTC). */
export function dateToLocalString(date: Date): string {
  const year = String(date.getFullYear())
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
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
    console.error(`Failed to parse date "${dateStr}":`, err)
    return dateStr
  }
}
