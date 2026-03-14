interface LabelSearchable {
  id: string
  names: readonly string[]
}

/** Returns true if the label id or any of its names contain the query (case-insensitive).
 *  A blank query matches every label. */
export function matchesLabelSearch(id: string, names: readonly string[], query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase()
  if (normalizedQuery === '') {
    return true
  }

  return (
    id.toLowerCase().includes(normalizedQuery) ||
    names.some((name) => name.toLowerCase().includes(normalizedQuery))
  )
}

/** Filter labels whose id or names match the query. Preserves the caller's concrete type. */
export function filterLabelsBySearch<T extends LabelSearchable>(labels: readonly T[], query: string): T[] {
  return labels.filter((label) => matchesLabelSearch(label.id, label.names, query))
}
