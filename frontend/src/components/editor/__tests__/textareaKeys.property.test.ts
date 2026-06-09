import { describe, expect, it } from 'vitest'
import fc from 'fast-check'

import {
  dedentLines,
  indentLines,
  lineEndTarget,
  pageTarget,
  smartHomeTarget,
} from '../textareaKeys'

const textArb = fc.string({ maxLength: 120 })

function normalizedSelection(len: number, startRaw: number, endRaw: number): [number, number] {
  const limit = len + 1
  const s = startRaw % limit
  const e = endRaw % limit
  return s <= e ? [s, e] : [e, s]
}

function lineBounds(value: string, caret: number): [number, number] {
  const start = value.lastIndexOf('\n', caret - 1) + 1
  const nl = value.indexOf('\n', caret)
  return [start, nl === -1 ? value.length : nl]
}

describe('indentLines property tests', () => {
  it('adds exactly two spaces per touched line', () => {
    fc.assert(
      fc.property(textArb, fc.nat({ max: 200 }), fc.nat({ max: 200 }), (value, a, b) => {
        const [s, e] = normalizedSelection(value.length, a, b)
        const result = indentLines(value, s, e)
        const lineDelta = result.value.length - value.length
        expect(lineDelta % 2).toBe(0)
        expect(lineDelta).toBeGreaterThanOrEqual(2)
      }),
      { numRuns: 400 },
    )
  })

  it('round-trips: dedent undoes indent for value and selection', () => {
    fc.assert(
      fc.property(textArb, fc.nat({ max: 200 }), fc.nat({ max: 200 }), (value, a, b) => {
        const [s, e] = normalizedSelection(value.length, a, b)
        const indented = indentLines(value, s, e)
        const restored = dedentLines(indented.value, indented.selectionStart, indented.selectionEnd)
        expect(restored.value).toBe(value)
        expect(restored.selectionStart).toBe(s)
        expect(restored.selectionEnd).toBe(e)
      }),
      { numRuns: 400 },
    )
  })
})

describe('dedentLines property tests', () => {
  it('never grows the value and keeps the selection in range', () => {
    fc.assert(
      fc.property(textArb, fc.nat({ max: 200 }), fc.nat({ max: 200 }), (value, a, b) => {
        const [s, e] = normalizedSelection(value.length, a, b)
        const result = dedentLines(value, s, e)
        expect(result.value.length).toBeLessThanOrEqual(value.length)
        expect(result.selectionStart).toBeGreaterThanOrEqual(0)
        expect(result.selectionEnd).toBeGreaterThanOrEqual(result.selectionStart)
        expect(result.selectionEnd).toBeLessThanOrEqual(result.value.length)
      }),
      { numRuns: 400 },
    )
  })
})

describe('caret-target property tests', () => {
  it('smart-home target always lies within the caret line', () => {
    fc.assert(
      fc.property(textArb, fc.nat({ max: 200 }), (value, raw) => {
        const caret = raw % (value.length + 1)
        const target = smartHomeTarget(value, caret)
        const [start, end] = lineBounds(value, caret)
        expect(target).toBeGreaterThanOrEqual(start)
        expect(target).toBeLessThanOrEqual(end)
      }),
      { numRuns: 500 },
    )
  })

  it('line-end target is the end of the caret line', () => {
    fc.assert(
      fc.property(textArb, fc.nat({ max: 200 }), (value, raw) => {
        const caret = raw % (value.length + 1)
        const [, end] = lineBounds(value, caret)
        expect(lineEndTarget(value, caret)).toBe(end)
      }),
      { numRuns: 500 },
    )
  })

  it('page target stays within the value bounds', () => {
    fc.assert(
      fc.property(
        textArb,
        fc.nat({ max: 200 }),
        fc.integer({ min: 1, max: 50 }),
        fc.constantFrom('up' as const, 'down' as const),
        (value, raw, pageLines, direction) => {
          const caret = raw % (value.length + 1)
          const target = pageTarget(value, caret, pageLines, direction)
          expect(target).toBeGreaterThanOrEqual(0)
          expect(target).toBeLessThanOrEqual(value.length)
        },
      ),
      { numRuns: 500 },
    )
  })
})
