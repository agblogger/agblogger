import { describe, expect, it } from 'vitest'

import { mapWithConcurrency } from '../concurrency'

describe('mapWithConcurrency', () => {
  it('maps every item and preserves input order', async () => {
    const items = [1, 2, 3, 4, 5, 6, 7]
    const result = await mapWithConcurrency(items, 3, (n) => Promise.resolve(n * 10))
    expect(result).toEqual([10, 20, 30, 40, 50, 60, 70])
  })

  it('never runs more workers at once than the configured limit', async () => {
    const items = Array.from({ length: 20 }, (_, index) => index)
    let inFlight = 0
    let maxInFlight = 0
    const result = await mapWithConcurrency(items, 4, async (n) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      await Promise.resolve()
      await Promise.resolve()
      inFlight -= 1
      return n
    })
    expect(maxInFlight).toBeLessThanOrEqual(4)
    expect(maxInFlight).toBeGreaterThan(1)
    expect(result).toEqual(items)
  })

  it('caps workers at one-per-item when items are fewer than the limit', async () => {
    let inFlight = 0
    let maxInFlight = 0
    await mapWithConcurrency([1, 2], 10, async (n) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      await Promise.resolve()
      inFlight -= 1
      return n
    })
    expect(maxInFlight).toBeLessThanOrEqual(2)
  })

  it('returns an empty array without invoking the worker for no items', async () => {
    let calls = 0
    const result = await mapWithConcurrency<number, string>([], 5, () => {
      calls += 1
      return Promise.resolve('x')
    })
    expect(result).toEqual([])
    expect(calls).toBe(0)
  })
})
