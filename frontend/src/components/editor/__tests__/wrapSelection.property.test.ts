import { describe, expect, it } from 'vitest'
import fc from 'fast-check'

import { wrapSelection, type WrapAction } from '../wrapSelection'

const textArb = fc.string({ maxLength: 120 })

const actionArb: fc.Arbitrary<WrapAction> = fc.record({
  before: fc.string({ maxLength: 8 }),
  after: fc.string({ maxLength: 8 }),
  placeholder: fc.string({ minLength: 1, maxLength: 32 }),
  block: fc.boolean(),
  linePrefix: fc.string({ minLength: 1, maxLength: 4 }),
}, { requiredKeys: ['before', 'after', 'placeholder', 'block'] })

function normalizedSelection(len: number, startRaw: number, endRaw: number): [number, number] {
  const limit = len + 1
  const s = startRaw % limit
  const e = endRaw % limit
  return s <= e ? [s, e] : [e, s]
}

describe('wrapSelection property tests', () => {
  it('always performs a deterministic splice/wrap transformation', () => {
    fc.assert(
      fc.property(
        textArb,
        fc.nat({ max: 500 }),
        fc.nat({ max: 500 }),
        actionArb,
        (value, startRaw, endRaw, action) => {
          const [selectionStart, selectionEnd] = normalizedSelection(value.length, startRaw, endRaw)

          const selected = value.slice(selectionStart, selectionEnd)
          const insertedText = selected.length > 0 ? selected : action.placeholder

          const blockPrefix =
            action.block === true &&
            selectionStart > 0 &&
            value[selectionStart - 1] !== '\n'
              ? '\n'
              : ''

          let expectedNewValue: string
          let expectedCursorStart: number
          let expectedCursorEnd: number

          if (action.linePrefix !== undefined) {
            const prefixed = insertedText
              .split('\n')
              .map((line) => action.linePrefix + line)
              .join('\n')
            expectedNewValue =
              value.slice(0, selectionStart) + blockPrefix + prefixed + value.slice(selectionEnd)
            expectedCursorStart = selectionStart + blockPrefix.length
            expectedCursorEnd = expectedCursorStart + prefixed.length
          } else {
            const expectedBefore = blockPrefix + action.before
            expectedNewValue =
              value.slice(0, selectionStart) +
              expectedBefore +
              insertedText +
              action.after +
              value.slice(selectionEnd)
            expectedCursorStart = selectionStart + expectedBefore.length
            expectedCursorEnd = expectedCursorStart + insertedText.length
          }

          const result = wrapSelection(value, selectionStart, selectionEnd, action)

          expect(result.newValue).toBe(expectedNewValue)
          expect(result.cursorStart).toBe(expectedCursorStart)
          expect(result.cursorEnd).toBe(expectedCursorEnd)
          const expectedSelectedText =
            action.linePrefix !== undefined
              ? insertedText
                  .split('\n')
                  .map((line) => action.linePrefix + line)
                  .join('\n')
              : insertedText

          expect(result.newValue.slice(result.cursorStart, result.cursorEnd)).toBe(
            expectedSelectedText,
          )
        },
      ),
      { numRuns: 500 },
    )
  })

  it('preserves untouched prefix/suffix around the replaced range', () => {
    fc.assert(
      fc.property(
        textArb,
        fc.nat({ max: 500 }),
        fc.nat({ max: 500 }),
        actionArb,
        (value, startRaw, endRaw, action) => {
          const [selectionStart, selectionEnd] = normalizedSelection(value.length, startRaw, endRaw)
          const result = wrapSelection(value, selectionStart, selectionEnd, action)

          const prefix = value.slice(0, selectionStart)
          expect(result.newValue.slice(0, prefix.length)).toBe(prefix)

          const suffix = value.slice(selectionEnd)
          if (suffix.length > 0) {
            expect(result.newValue.slice(-suffix.length)).toBe(suffix)
          }
        },
      ),
      { numRuns: 400 },
    )
  })

  it('injects an extra leading newline only for block actions not at line start', () => {
    fc.assert(
      fc.property(textArb, fc.string({ minLength: 1, maxLength: 8 }), (value, before) => {
        const selectionStart = value.length
        const selectionEnd = value.length

        const blockResult = wrapSelection(value, selectionStart, selectionEnd, {
          before,
          after: '',
          placeholder: 'x',
          block: true,
        })

        const inlineResult = wrapSelection(value, selectionStart, selectionEnd, {
          before,
          after: '',
          placeholder: 'x',
          block: false,
        })

        const shouldPrefixWithNewline = value.length > 0 && value[value.length - 1] !== '\n'
        const expectedBlockPrefix = shouldPrefixWithNewline ? `\n${before}` : before

        expect(blockResult.newValue).toBe(`${value}${expectedBlockPrefix}x`)
        expect(inlineResult.newValue).toBe(`${value}${before}x`)
      }),
      { numRuns: 300 },
    )
  })

  it('injects an extra leading newline for linePrefix block actions not at line start', () => {
    fc.assert(
      fc.property(
        textArb,
        fc.string({ minLength: 1, maxLength: 4 }),
        (value, linePrefix) => {
          const selectionStart = value.length
          const selectionEnd = value.length

          const blockResult = wrapSelection(value, selectionStart, selectionEnd, {
            before: '',
            after: '',
            placeholder: 'x',
            block: true,
            linePrefix,
          })

          const inlineResult = wrapSelection(value, selectionStart, selectionEnd, {
            before: '',
            after: '',
            placeholder: 'x',
            block: false,
            linePrefix,
          })

          const shouldPrefixWithNewline = value.length > 0 && value[value.length - 1] !== '\n'
          const expectedBlockValue = shouldPrefixWithNewline
            ? `${value}\n${linePrefix}x`
            : `${value}${linePrefix}x`

          expect(blockResult.newValue).toBe(expectedBlockValue)
          expect(inlineResult.newValue).toBe(`${value}${linePrefix}x`)
        },
      ),
      { numRuns: 300 },
    )
  })

  it('never returns out-of-range cursor coordinates', () => {
    fc.assert(
      fc.property(
        textArb,
        fc.nat({ max: 500 }),
        fc.nat({ max: 500 }),
        actionArb,
        (value, startRaw, endRaw, action) => {
          const [selectionStart, selectionEnd] = normalizedSelection(value.length, startRaw, endRaw)
          const result = wrapSelection(value, selectionStart, selectionEnd, action)

          expect(result.cursorStart).toBeGreaterThanOrEqual(0)
          expect(result.cursorEnd).toBeGreaterThanOrEqual(result.cursorStart)
          expect(result.cursorEnd).toBeLessThanOrEqual(result.newValue.length)
        },
      ),
      { numRuns: 500 },
    )
  })
})
