import { format, formatDistanceToNow, parseISO, differenceInDays } from 'date-fns'

/**
 * Normalise a backend ISO timestamp (space-separated, two-digit offset)
 * into a standard ISO string suitable for `parseISO`.
 */
function normalise(dateStr: string): string {
  return dateStr.replace(' ', 'T').replace(/([+-])(\d{2})$/, '$1$2:00')
}

/**
 * Parse a backend ISO timestamp and format it for display.
 *
 * The backend emits timestamps with a space instead of 'T' and may
 * use a bare two-digit UTC offset (e.g. "+00" instead of "+00:00").
 * This helper normalises both quirks before parsing.
 */
export function formatDate(dateStr: string, pattern = 'MMM d, yyyy'): string {
  try {
    return format(parseISO(normalise(dateStr)), pattern)
  } catch (err) {
    console.warn(`Failed to parse date "${dateStr}":`, err)
    return dateStr || ''
  }
}

/**
 * Format a date string as relative ("3 days ago") when recent (< 7 days),
 * otherwise fall back to "MMM d, yyyy".
 */
export function formatRelativeDate(dateStr: string): string {
  try {
    const date = parseISO(normalise(dateStr))
    if (Math.abs(differenceInDays(new Date(), date)) < 7) {
      return formatDistanceToNow(date, { addSuffix: true })
    }
    return format(date, 'MMM d, yyyy')
  } catch (err) {
    console.warn(`Failed to parse date "${dateStr}":`, err)
    return dateStr || ''
  }
}

/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the start of that day in the user's local timezone.
 */
export function localDateToUtcStart(dateStr: string): string {
  if (!dateStr) return ''
  const [year, month, day] = dateStr.split('-').map(Number)
  const local = new Date(year, month - 1, day, 0, 0, 0, 0)
  return local.toISOString()
}

/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the end of that day in the user's local timezone.
 */
export function localDateToUtcEnd(dateStr: string): string {
  if (!dateStr) return ''
  const [year, month, day] = dateStr.split('-').map(Number)
  const local = new Date(year, month - 1, day, 23, 59, 59, 999)
  return local.toISOString()
}
