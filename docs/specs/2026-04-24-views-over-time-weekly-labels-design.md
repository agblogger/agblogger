# Design: ViewsOverTimeChart Weekly Labels & Locale-Aware Dates

**Date:** 2026-04-24

## Problem

The `ViewsOverTimeChart` component silently switches to weekly bucketing when the selected date range exceeds 30 days (i.e. the 90-day range). In weekly mode each bar represents 7 days of aggregated views, but the x-axis label still shows only the week-start date formatted as `MM-DD` — a hardcoded US convention. Users cannot tell whether a bar represents one day or one week, nor can non-US users read the date format naturally.

## Goal

- Make weekly bars unambiguous: label each bar with the date range it covers.
- Use browser locale for all date formatting in the chart (no hardcoded separators or month/day order).

## Scope

Single file: `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx`.  
Read-only dependency: `frontend/src/utils/date.ts` (`formatLocalDate`).  
No API, backend, or other component changes.

## Design

### Locale-aware short date helper

Replace the `formatDateLabel` function (which splits a `YYYY-MM-DD` string and produces `MM-DD`) with a `formatShortDate` helper:

```ts
function formatShortDate(date: string): string {
  return formatLocalDate(date, { month: 'numeric', day: 'numeric' })
}
```

`formatLocalDate` already calls `Intl.DateTimeFormat(undefined, options)`, which honours the browser locale.

### Daily mode labels (≤30 days)

Map each day to `formatShortDate(d.date)`. Examples: `1/15` (en-US), `15.1` (de-DE), `15/1` (fr-FR).

### Weekly mode labels (>30 days)

`bucketWeekly` computes both the start and end date of each 7-day chunk and produces a range label:

```
`${formatShortDate(start)}–${formatShortDate(end)}`
```

Examples: `1/15–1/21` (en-US), `15.1–21.1` (de-DE). The separator is an en dash (`–`).

### Chart title

A derived boolean `isWeekly = days.length > 30` (computed outside `useMemo`, used both for data bucketing and the title):

- Weekly mode: `"Views per week"`
- Daily mode: `"Views over time"`

### No changes to `date.ts`

`formatLocalDate` is already locale-aware and accepts `Intl.DateTimeFormatOptions`. No new exports needed.

## Testing

Update existing tests in `ViewsOverTimeChart.test.tsx`:

- `"renders chart when days > 30 (weekly bucketing)"` — update assertion from `"Views over time"` to `"Views per week"`.

Add new tests:

- Weekly title: `days.length > 30` renders heading `"Views per week"`.
- Weekly label shape: rendered label text contains `–` (en dash).
- Daily title: `days.length <= 30` renders heading `"Views over time"`.
- Daily label format: rendered label text matches the output of `Intl.DateTimeFormat(undefined, { month: 'numeric', day: 'numeric' }).format(new Date('2024-01-15'))`, confirming locale-aware formatting is used instead of the hardcoded `MM-DD` pattern.

## Out of Scope

- Tooltip formatting (Recharts default tooltip is acceptable).
- Other charts in the analytics panel (no weekly bucketing elsewhere).
- Any backend or API changes.
