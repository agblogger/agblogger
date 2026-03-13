import { describe, expect, it } from 'vitest'

import { filterLabelsBySearch, matchesLabelSearch } from '../searchUtils'

const labels = [
  { id: 'swe', names: ['software engineering'] },
  { id: 'math', names: ['mathematics'] },
  { id: 'cs', names: ['computer science'] },
]

describe('searchUtils', () => {
  it('matches label ids case-insensitively', () => {
    expect(matchesLabelSearch('swe', ['software engineering'], 'SW')).toBe(true)
  })

  it('matches label names case-insensitively', () => {
    expect(matchesLabelSearch('swe', ['software engineering'], 'Software')).toBe(true)
  })

  it('treats blank queries as a match', () => {
    expect(matchesLabelSearch('swe', ['software engineering'], '   ')).toBe(true)
  })

  it('filters labels by id or name', () => {
    expect(filterLabelsBySearch(labels, 'science')).toEqual([
      { id: 'cs', names: ['computer science'] },
    ])
  })
})
