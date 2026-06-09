import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  calibrateEditorOffsets,
  editorToPreview,
  previewToEditor,
  type SyncPoint,
} from '@/hooks/useScrollSync'

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

describe('calibrateEditorOffsets — mirror-to-textarea height calibration', () => {
  it('is the identity when the mirror and textarea content heights match', () => {
    fc.assert(
      fc.property(
        fc.array(fc.double({ min: 0, max: 100_000, noNaN: true }), { maxLength: 30 }),
        fc.double({ min: 0, max: 100, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        (offsets, padTop, height) => {
          const out = calibrateEditorOffsets(offsets, padTop, height, height)
          out.forEach((v, i) => expect(v).toBeCloseTo(offsets[i]!, 6))
        },
      ),
    )
  })

  it('keeps the padding-top anchor fixed regardless of scale', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 100, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        (padTop, mirrorH, realH) => {
          const [out] = calibrateEditorOffsets([padTop], padTop, mirrorH, realH)
          expect(out).toBeCloseTo(padTop, 6)
        },
      ),
    )
  })

  it('preserves ordering and scales the text region toward the real height', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 50, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        (padTop, mirrorH, realH) => {
          const a = padTop + 100
          const b = padTop + 300
          const [oa, ob] = calibrateEditorOffsets([a, b], padTop, mirrorH, realH)
          expect(oa!).toBeLessThanOrEqual(ob! + 1e-9)
          // scale > 1 (real taller than mirror) pushes points away from the anchor;
          // scale < 1 pulls them toward it.
          if (realH > mirrorH) expect(oa! - padTop).toBeGreaterThanOrEqual(a - padTop - 1e-9)
          else expect(oa! - padTop).toBeLessThanOrEqual(a - padTop + 1e-9)
        },
      ),
    )
  })

  it('returns offsets unchanged for degenerate (non-positive or non-finite) heights', () => {
    const offs = [0, 10, 25, 100]
    expect(calibrateEditorOffsets(offs, 8, 0, 500)).toEqual(offs)
    expect(calibrateEditorOffsets(offs, 8, 500, 0)).toEqual(offs)
    expect(calibrateEditorOffsets(offs, 8, -5, 500)).toEqual(offs)
    expect(calibrateEditorOffsets(offs, 8, Number.NaN, 500)).toEqual(offs)
    expect(calibrateEditorOffsets(offs, 8, 500, Number.POSITIVE_INFINITY)).toEqual(offs)
  })
})
