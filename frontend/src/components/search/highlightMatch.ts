export interface HighlightSegment {
  text: string
  match: boolean
}

/**
 * Split a title into segments based on query term matches.
 * Returns an array of segments, each marked as a match or not.
 * The joined text of all segments always equals the original title.
 */
export function highlightParts(title: string, query: string): HighlightSegment[] {
  const terms = query.trim().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return [{ text: title, match: false }]

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
    .map((text, i) => ({ text, match: i % 2 === 1 }))
    .filter((seg) => seg.text !== '')
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
