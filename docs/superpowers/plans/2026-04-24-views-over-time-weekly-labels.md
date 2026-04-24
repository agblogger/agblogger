# ViewsOverTimeChart Weekly Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `ViewsOverTimeChart` so weekly-bucketed bars show a locale-aware date-range label and the chart title reflects the aggregation period.

**Architecture:** Two changes to a single component file — (1) replace the hardcoded `MM-DD` formatter with `formatLocalDate` from `utils/date.ts`, and (2) derive an `isWeekly` flag from `days.length` to switch the chart title and produce `start–end` range labels in weekly mode.

**Tech Stack:** React, Recharts, Intl.DateTimeFormat (via existing `formatLocalDate` utility), Vitest + React Testing Library.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx` |
| Modify | `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx` |

---

### Task 1: Write failing tests

**Files:**
- Modify: `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx`

- [ ] **Step 1: Replace the existing weekly-mode heading assertion and add new test cases**

Open `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx` and replace its entire contents with:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ViewsOverTimeChart from '../ViewsOverTimeChart'
import type { DailyViewCount } from '@/api/client'

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function makeDays(count: number): DailyViewCount[] {
  return Array.from({ length: count }, (_, i) => ({
    date: `2024-01-${String(i + 1).padStart(2, '0')}`,
    views: i + 1,
  }))
}

describe('ViewsOverTimeChart', () => {
  it('renders "Views over time" heading', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('shows empty state when days is empty', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText('No data for selected range.')).toBeInTheDocument()
  })

  it('renders "Views over time" heading for ≤30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(7)} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
    expect(screen.queryByText('Views per week')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for ≤30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(30)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('renders "Views per week" heading for >30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.getByText('Views per week')).toBeInTheDocument()
    expect(screen.queryByText('Views over time')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for >30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
  })

  it('weekly labels contain an en dash range separator', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    // Recharts renders XAxis ticks as SVG <text> nodes; at least one should
    // contain the en dash (–) that separates the start and end of each week.
    const enDashLabels = screen.queryAllByText(/–/)
    expect(enDashLabels.length).toBeGreaterThan(0)
  })

  it('daily labels use locale-aware short date format', () => {
    render(<ViewsOverTimeChart days={makeDays(7)} />)
    // The first day is 2024-01-01. Its locale label must match what
    // Intl.DateTimeFormat produces — not the hardcoded "01-01" pattern.
    const expected = new Intl.DateTimeFormat(undefined, {
      month: 'numeric',
      day: 'numeric',
    }).format(new Date('2024-01-01'))
    const labelNodes = screen.queryAllByText(expected)
    expect(labelNodes.length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run the new tests and confirm the right ones fail**

```bash
just test-frontend 2>&1 | grep -A 3 "ViewsOverTimeChart"
```

Expected failures (current implementation uses old heading/labels):
- `renders "Views per week" heading for >30 days` — FAIL (heading still says "Views over time")
- `renders chart when days > 30 (weekly bucketing)` removed and replaced; new weekly tests fail
- `weekly labels contain an en dash range separator` — FAIL (labels are currently `MM-DD`)
- `daily labels use locale-aware short date format` — may FAIL if jsdom locale differs from `01-01`

All other tests should still pass.

---

### Task 2: Implement the fix

**Files:**
- Modify: `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx`

- [ ] **Step 1: Replace the file contents with the locale-aware implementation**

Replace the entire contents of `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx` with:

```tsx
import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { DailyViewCount } from '@/api/client'
import { formatLocalDate } from '@/utils/date'

interface ViewsOverTimeChartProps {
  days: DailyViewCount[]
}

interface ChartPoint {
  label: string
  views: number
}

function formatShortDate(date: string): string {
  return formatLocalDate(date, { month: 'numeric', day: 'numeric' })
}

function bucketWeekly(days: DailyViewCount[]): ChartPoint[] {
  const buckets: ChartPoint[] = []
  for (let i = 0; i < days.length; i += 7) {
    const chunk = days.slice(i, i + 7)
    const total = chunk.reduce((sum, d) => sum + d.views, 0)
    const start = chunk[0]?.date ?? ''
    const end = chunk[chunk.length - 1]?.date ?? start
    buckets.push({ label: `${formatShortDate(start)}–${formatShortDate(end)}`, views: total })
  }
  return buckets
}

export default function ViewsOverTimeChart({ days }: ViewsOverTimeChartProps) {
  const isWeekly = days.length > 30
  const chartData = useMemo<ChartPoint[]>(() => {
    if (days.length === 0) return []
    if (days.length <= 30) {
      return days.map((d) => ({ label: formatShortDate(d.date), views: d.views }))
    }
    return bucketWeekly(days)
  }, [days])

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">
        {isWeekly ? 'Views per week' : 'Views over time'}
      </h3>
      {days.length === 0 ? (
        <p className="text-muted text-sm">No data for selected range.</p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart
            data={chartData}
            margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
          >
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar
              dataKey="views"
              fill="var(--color-accent, #6366f1)"
              fillOpacity={0.75}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run the tests and confirm all pass**

```bash
just test-frontend 2>&1 | grep -A 3 "ViewsOverTimeChart"
```

Expected: all 8 `ViewsOverTimeChart` tests PASS.

> **Note on the en-dash test:** Recharts renders tick labels as SVG `<text>` nodes. If `queryAllByText(/–/)` returns 0 nodes in this jsdom environment (recharts may skip SVG rendering), the test will still catch the most important regressions via the heading tests. If it fails for environment reasons, adjust the test to check the label format via a pure helper export instead (see note in Task 3).

- [ ] **Step 3: Run the full frontend check**

```bash
just check-frontend
```

Expected: all checks pass (lint, types, tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx \
        frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx
git commit -m "fix: show locale-aware weekly date ranges in ViewsOverTimeChart"
```

---

### Task 3: (Conditional) Fix en-dash test if Recharts doesn't render SVG ticks in jsdom

Only do this task if the `weekly labels contain an en dash range separator` test failed in Task 2 because recharts didn't render tick nodes (not because of a logic error).

**Files:**
- Modify: `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx`
- Modify: `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx`

- [ ] **Step 1: Export `bucketWeekly` for direct unit testing**

In `ViewsOverTimeChart.tsx`, change the function declaration from:

```ts
function bucketWeekly(days: DailyViewCount[]): ChartPoint[] {
```

to:

```ts
export function bucketWeekly(days: DailyViewCount[]): ChartPoint[] {
```

- [ ] **Step 2: Replace the en-dash test with a direct unit test**

In `ViewsOverTimeChart.test.tsx`, replace:

```ts
it('weekly labels contain an en dash range separator', () => {
  render(<ViewsOverTimeChart days={makeDays(90)} />)
  const enDashLabels = screen.queryAllByText(/–/)
  expect(enDashLabels.length).toBeGreaterThan(0)
})
```

with:

```ts
import { bucketWeekly } from '../ViewsOverTimeChart'

// ... inside describe block:
it('weekly labels contain an en dash range separator', () => {
  const days = makeDays(14) // two full weeks
  const buckets = bucketWeekly(days)
  expect(buckets).toHaveLength(2)
  expect(buckets[0]?.label).toContain('–')
  expect(buckets[1]?.label).toContain('–')
})
```

- [ ] **Step 3: Run tests**

```bash
just test-frontend 2>&1 | grep -A 3 "ViewsOverTimeChart"
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx \
        frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx
git commit -m "test: export bucketWeekly for direct unit testing of label format"
```

---

### Task 4: Verify in browser

- [ ] **Step 1: Start the dev server**

```bash
just start
```

- [ ] **Step 2: Open the admin analytics panel in a browser**

Navigate to `http://localhost:5173`, log in, open the Admin panel, go to Analytics, and select the **90-day** date range.

- [ ] **Step 3: Verify**

- The chart heading reads **"Views per week"** (not "Views over time").
- Each bar's x-axis label shows a date range in the system locale format (e.g. `1/1–1/7` for en-US, `1.1–7.1` for de-DE).
- Switch to **7-day** or **30-day** range: heading reads **"Views over time"**, labels show single locale-formatted dates.

- [ ] **Step 4: Stop the dev server**

```bash
just stop
```

- [ ] **Step 5: Run the full gate**

```bash
just check
```

Expected: all checks pass.
