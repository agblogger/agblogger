import { describe, it, expect } from 'vitest'
import { highlightMatch } from '../highlightMatch'

describe('highlightMatch', () => {
  it('wraps matching substring in mark tags', () => {
    expect(highlightMatch('Database Migration Guide', 'migrat')).toBe(
      'Database <mark>Migrat</mark>ion Guide',
    )
  })

  it('highlights multiple terms', () => {
    expect(highlightMatch('Running Migrations in Production', 'running prod')).toBe(
      '<mark>Running</mark> Migrations in <mark>Prod</mark>uction',
    )
  })

  it('is case-insensitive', () => {
    expect(highlightMatch('Hello World', 'hello')).toBe('<mark>Hello</mark> World')
  })

  it('returns original text when no match', () => {
    expect(highlightMatch('Hello World', 'xyz')).toBe('Hello World')
  })

  it('returns original text for empty query', () => {
    expect(highlightMatch('Hello World', '')).toBe('Hello World')
    expect(highlightMatch('Hello World', '   ')).toBe('Hello World')
  })

  it('escapes HTML in title text', () => {
    expect(highlightMatch('<script>alert(1)</script>', 'script')).toBe(
      '&lt;<mark>script</mark>&gt;alert(1)&lt;/<mark>script</mark>&gt;',
    )
  })

  it('escapes ampersands in title text', () => {
    expect(highlightMatch('AT&T Guide', 'guide')).toBe('AT&amp;T <mark>Guide</mark>')
  })

  it('handles overlapping match regions by taking first match', () => {
    expect(highlightMatch('testing', 'test testing')).toBe('<mark>testing</mark>')
  })

  it('handles regex metacharacters in query without crashing', () => {
    expect(highlightMatch('Learning C++ Basics', 'c++')).toBe(
      'Learning <mark>C++</mark> Basics',
    )
    expect(highlightMatch('Is this a question?', 'question?')).toBe(
      'Is this a <mark>question?</mark>',
    )
    expect(highlightMatch('[Draft] My Post', '[draft]')).toBe(
      '<mark>[Draft]</mark> My Post',
    )
    expect(highlightMatch('config.yaml setup', 'config.yaml')).toBe(
      '<mark>config.yaml</mark> setup',
    )
    expect(highlightMatch('Price is $5', '$5')).toBe(
      'Price is <mark>$5</mark>',
    )
  })

  it('handles empty title', () => {
    expect(highlightMatch('', 'hello')).toBe('')
  })
})
