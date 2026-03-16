/**
 * Highlight query term matches in a title string.
 * Returns an HTML string with matches wrapped in <mark> tags.
 * The title is split on query matches first, then each segment
 * is HTML-escaped individually before matches are wrapped.
 */
export function highlightMatch(title: string, query: string): string {
  const terms = query.trim().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return escapeHtml(title)

  // Build a single regex matching any term (longest first so e.g. "testing" is matched before "test")
  const sorted = [...terms].sort((a, b) => b.length - a.length)
  const pattern = new RegExp(
    `(${sorted.map(escapeRegex).join('|')})`,
    'gi',
  )

  // split() with a single capture group returns alternating [non-match, match, non-match, ...]
  // Odd-indexed parts are always the captured matches.
  const parts = title.split(pattern)
  return parts
    .map((part, i) => (i % 2 === 1 ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join('')
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
