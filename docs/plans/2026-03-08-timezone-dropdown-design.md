# Timezone Searchable Dropdown — Design

## Summary

Replace the plain text input for timezone in the admin panel with a searchable combobox dropdown showing IANA timezones with major city names in brackets.

## UI Behavior

- **Component**: Custom combobox (text input + filtered dropdown list)
- **Display format**: `America/New_York (New York)` — city name extracted from the IANA identifier, underscores replaced with spaces
- **Order**:
  1. User's detected timezone via `Intl.DateTimeFormat().resolvedOptions().timeZone` — labeled "(detected)"
  2. `UTC` — always second
  3. Remaining timezones sorted alphabetically
- **Search**: Filters on both the IANA key and the city name, case-insensitive
- **Selection**: Clicking an option or pressing Enter selects it, stores the raw IANA string (e.g. `America/New_York`)
- **Keyboard**: Arrow keys navigate, Escape closes, typing filters
- **Click outside**: Closes the dropdown

## Data Flow

No backend schema changes — the stored value remains a plain IANA timezone string. The combobox is purely a frontend UX improvement over the current text input.

## Backend Validation

Add validation to the `PUT /api/admin/site` endpoint so invalid timezones are rejected with a 422 rather than silently accepted and falling back to UTC on next restart.

## Timezone List Source

Use `Intl.supportedValuesOf('timeZone')` in the browser — returns the full IANA list without needing a backend endpoint.

## Testing

- Frontend: test rendering, filtering, selection, detected timezone appearing
- Backend: test that invalid timezone is rejected with 422
