import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { editorToPreview, previewToEditor, type SyncPoint } from '@/hooks/useScrollSync'

const TOL = 1e-6

/** Build sync points whose editorPx and previewPx are both non-decreasing. */
const arbPoints = fc
  .array(
    fc.record({
      e: fc.double({ min: 0, max: 1_000_000, noNaN: true }),
      p: fc.double({ min: 0, max: 1_000_000, noNaN: true }),
    }),
    { minLength: 1, maxLength: 25 },
  )
  .map((pairs): SyncPoint[] => {
    const es = pairs.map((x) => x.e).sort((a, b) => a - b)
    const ps = pairs.map((x) => x.p).sort((a, b) => a - b)
    return es.map((e, i) => ({ editorPx: e, previewPx: ps[i] }) as SyncPoint)
  })

/** Build sync points with strictly increasing editorPx AND previewPx. */
const arbStrictPoints = fc
  .uniqueArray(fc.integer({ min: 0, max: 1_000_000 }), { minLength: 2, maxLength: 25 })
  .chain((es) =>
    fc
      .uniqueArray(fc.integer({ min: 0, max: 1_000_000 }), {
        minLength: es.length,
        maxLength: es.length,
      })
      .map((ps): SyncPoint[] => {
        const se = [...es].sort((a, b) => a - b)
        const sp = [...ps].sort((a, b) => a - b)
        return se.map((e, i) => ({ editorPx: e, previewPx: sp[i] }) as SyncPoint)
      }),
  )

describe('editorToPreview / previewToEditor — pure interpolation', () => {
  it('empty points map to 0', () => {
    expect(editorToPreview([], 123)).toBe(0)
    expect(previewToEditor([], 123)).toBe(0)
  })

  it('editorToPreview is monotonic non-decreasing in scrollTop', () => {
    fc.assert(
      fc.property(
        arbPoints,
        fc.double({ min: 0, max: 1_500_000, noNaN: true }),
        fc.double({ min: 0, max: 1_500_000, noNaN: true }),
        (points, a, b) => {
          const lo = Math.min(a, b)
          const hi = Math.max(a, b)
          expect(editorToPreview(points, lo)).toBeLessThanOrEqual(editorToPreview(points, hi) + TOL)
        },
      ),
    )
  })

  it('previewToEditor is monotonic non-decreasing in scrollTop', () => {
    fc.assert(
      fc.property(
        arbPoints,
        fc.double({ min: 0, max: 1_500_000, noNaN: true }),
        fc.double({ min: 0, max: 1_500_000, noNaN: true }),
        (points, a, b) => {
          const lo = Math.min(a, b)
          const hi = Math.max(a, b)
          expect(previewToEditor(points, lo)).toBeLessThanOrEqual(previewToEditor(points, hi) + TOL)
        },
      ),
    )
  })

  it('editorToPreview stays within the previewPx range of the points', () => {
    fc.assert(
      fc.property(arbPoints, fc.double({ min: 0, max: 1_500_000, noNaN: true }), (points, s) => {
        const minP = points[0]!.previewPx
        const maxP = points[points.length - 1]!.previewPx
        const r = editorToPreview(points, s)
        expect(r).toBeGreaterThanOrEqual(minP - TOL)
        expect(r).toBeLessThanOrEqual(maxP + TOL)
      }),
    )
  })

  it('maps below-first and above-last scroll positions to the endpoints', () => {
    fc.assert(
      fc.property(arbStrictPoints, (points) => {
        const first = points[0]!
        const last = points[points.length - 1]!
        expect(editorToPreview(points, first.editorPx - 50)).toBeCloseTo(first.previewPx, 6)
        expect(editorToPreview(points, last.editorPx + 50)).toBeCloseTo(last.previewPx, 6)
      }),
    )
  })

  it('returns the exact anchor position at each anchor (strictly increasing points)', () => {
    fc.assert(
      fc.property(arbStrictPoints, (points) => {
        for (const pt of points) {
          expect(editorToPreview(points, pt.editorPx)).toBeCloseTo(pt.previewPx, 6)
          expect(previewToEditor(points, pt.previewPx)).toBeCloseTo(pt.editorPx, 6)
        }
      }),
    )
  })

  it('round-trips editor->preview->editor at every anchor', () => {
    fc.assert(
      fc.property(arbStrictPoints, (points) => {
        for (const pt of points) {
          const fwd = editorToPreview(points, pt.editorPx)
          expect(previewToEditor(points, fwd)).toBeCloseTo(pt.editorPx, 6)
        }
      }),
    )
  })
})
