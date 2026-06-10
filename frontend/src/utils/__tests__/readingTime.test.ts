import { describe, expect, it } from 'vitest'
import { readingTime } from '../readingTime'

describe('readingTime', () => {
  it('returns 1 min read for zero words', () => {
    expect(readingTime(0)).toBe(`1 min read · ${(0).toLocaleString()} words`)
  })

  it('returns 1 min read for a short post (under 200 words)', () => {
    expect(readingTime(150)).toBe(`1 min read · ${(150).toLocaleString()} words`)
  })

  it('returns 1 min read for exactly 200 words', () => {
    expect(readingTime(200)).toBe(`1 min read · ${(200).toLocaleString()} words`)
  })

  it('returns 2 min read for 201 words', () => {
    expect(readingTime(201)).toBe(`2 min read · ${(201).toLocaleString()} words`)
  })

  it('returns 5 min read for a 1000-word post', () => {
    expect(readingTime(1000)).toBe(`5 min read · ${(1000).toLocaleString()} words`)
  })

  it('uses locale-formatted word count', () => {
    const result = readingTime(12345)
    expect(result).toContain((12345).toLocaleString())
  })
})
