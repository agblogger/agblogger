import { format, parseISO } from 'date-fns'

/**
 * Parse a backend ISO timestamp and format it for display.
 *
 * The backend emits timestamps with a space instead of 'T' and may
 * use a bare two-digit UTC offset (e.g. "+00" instead of "+00:00").
 * This helper normalises both quirks before parsing.
 */
export function formatDate(dateStr: string, pattern = 'MMM d, yyyy'): string {
  try {
    const normalised = dateStr.replace(' ', 'T').replace(/([+-])(\d{2})$/, '$1$2:00')
    return format(parseISO(normalised), pattern)
  } catch {
    return dateStr.split(' ')[0] ?? ''
  }
}
