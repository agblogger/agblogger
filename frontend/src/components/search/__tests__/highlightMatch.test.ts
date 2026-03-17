import { describe, it, expect } from 'vitest'
import { highlightParts } from '../highlightMatch'

describe('highlightParts', () => {
  it('marks matching substring', () => {
    expect(highlightParts('Database Migration Guide', 'migrat')).toEqual([
      { text: 'Database ', match: false },
      { text: 'Migrat', match: true },
      { text: 'ion Guide', match: false },
    ])
  })

  it('highlights multiple terms', () => {
    expect(highlightParts('Running Migrations in Production', 'running prod')).toEqual([
      { text: 'Running', match: true },
      { text: ' Migrations in ', match: false },
      { text: 'Prod', match: true },
      { text: 'uction', match: false },
    ])
  })

  it('is case-insensitive', () => {
    expect(highlightParts('Hello World', 'hello')).toEqual([
      { text: 'Hello', match: true },
      { text: ' World', match: false },
    ])
  })

  it('returns original text when no match', () => {
    expect(highlightParts('Hello World', 'xyz')).toEqual([
      { text: 'Hello World', match: false },
    ])
  })

  it('returns original text for empty query', () => {
    expect(highlightParts('Hello World', '')).toEqual([
      { text: 'Hello World', match: false },
    ])
    expect(highlightParts('Hello World', '   ')).toEqual([
      { text: 'Hello World', match: false },
    ])
  })

  it('preserves HTML characters in text (no escaping needed)', () => {
    expect(highlightParts('<script>alert(1)</script>', 'script')).toEqual([
      { text: '<', match: false },
      { text: 'script', match: true },
      { text: '>alert(1)</', match: false },
      { text: 'script', match: true },
      { text: '>', match: false },
    ])
  })

  it('preserves ampersands in text', () => {
    expect(highlightParts('AT&T Guide', 'guide')).toEqual([
      { text: 'AT&T ', match: false },
      { text: 'Guide', match: true },
    ])
  })

  it('handles overlapping match regions by taking first match', () => {
    expect(highlightParts('testing', 'test testing')).toEqual([
      { text: 'testing', match: true },
    ])
  })

  it('handles regex metacharacters in query without crashing', () => {
    expect(highlightParts('Learning C++ Basics', 'c++')).toEqual([
      { text: 'Learning ', match: false },
      { text: 'C++', match: true },
      { text: ' Basics', match: false },
    ])
    expect(highlightParts('Is this a question?', 'question?')).toEqual([
      { text: 'Is this a ', match: false },
      { text: 'question?', match: true },
    ])
    expect(highlightParts('[Draft] My Post', '[draft]')).toEqual([
      { text: '[Draft]', match: true },
      { text: ' My Post', match: false },
    ])
    expect(highlightParts('config.yaml setup', 'config.yaml')).toEqual([
      { text: 'config.yaml', match: true },
      { text: ' setup', match: false },
    ])
    expect(highlightParts('Price is $5', '$5')).toEqual([
      { text: 'Price is ', match: false },
      { text: '$5', match: true },
    ])
  })

  it('handles empty title', () => {
    expect(highlightParts('', 'hello')).toEqual([])
  })

  it('joined text always equals original title', () => {
    const cases = [
      ['Database Migration Guide', 'migrat'],
      ['Running Migrations in Production', 'running prod'],
      ['<script>alert(1)</script>', 'script'],
      ['AT&T Guide', 'guide'],
      ['testing', 'test testing'],
      ['Hello World', 'xyz'],
      ['Hello World', ''],
    ] as const
    for (const [title, query] of cases) {
      const parts = highlightParts(title, query)
      expect(parts.map((p) => p.text).join('')).toBe(title)
    }
  })
})
