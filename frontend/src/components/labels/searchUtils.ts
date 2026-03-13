interface LabelSearchable {
  id: string
  names: readonly string[]
}

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

export function filterLabelsBySearch<T extends LabelSearchable>(labels: readonly T[], query: string): T[] {
  return labels.filter((label) => matchesLabelSearch(label.id, label.names, query))
}
