import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import TimezoneCombobox from '../TimezoneCombobox'

const MOCK_TIMEZONES = [
  'America/Los_Angeles',
  'America/New_York',
  'Asia/Tokyo',
  'Europe/London',
  'Pacific/Auckland',
  'UTC',
]

let originalIntl: typeof Intl

beforeEach(() => {
  originalIntl = globalThis.Intl
  vi.stubGlobal('Intl', {
    ...Intl,
    supportedValuesOf: vi.fn().mockReturnValue(MOCK_TIMEZONES),
    DateTimeFormat: class extends Intl.DateTimeFormat {
      override resolvedOptions() {
        return { ...super.resolvedOptions(), timeZone: 'America/New_York' }
      }
    },
  })
})

afterEach(() => {
  globalThis.Intl = originalIntl
  vi.restoreAllMocks()
})

describe('TimezoneCombobox', () => {
  it('renders with current value displayed in display format', () => {
    render(
      <TimezoneCombobox value="America/New_York" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    expect(input).toHaveValue('America/New_York (New York) (detected)')
  })

  it('shows dropdown on focus/click', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('shows detected timezone first, then UTC, then rest alphabetically', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    const listbox = screen.getByRole('listbox')
    const options = within(listbox).getAllByRole('option')

    // First: detected timezone (America/New_York)
    expect(options[0]).toHaveTextContent('America/New_York (New York) (detected)')
    // Second: UTC
    expect(options[1]).toHaveTextContent('UTC')
    // Rest sorted alphabetically
    expect(options[2]).toHaveTextContent('America/Los_Angeles (Los Angeles)')
    expect(options[3]).toHaveTextContent('Asia/Tokyo (Tokyo)')
    expect(options[4]).toHaveTextContent('Europe/London (London)')
    expect(options[5]).toHaveTextContent('Pacific/Auckland (Auckland)')
  })

  it('shows UTC with (detected) suffix when UTC is the detected timezone', async () => {
    vi.stubGlobal('Intl', {
      ...Intl,
      supportedValuesOf: vi.fn().mockReturnValue(MOCK_TIMEZONES),
      DateTimeFormat: class extends Intl.DateTimeFormat {
        override resolvedOptions() {
          return { ...super.resolvedOptions(), timeZone: 'UTC' }
        }
      },
    })

    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    const listbox = screen.getByRole('listbox')
    const options = within(listbox).getAllByRole('option')

    // UTC with (detected) should be first and only appear once
    expect(options[0]).toHaveTextContent('UTC (detected)')
    // The second should NOT be another UTC
    expect(options[1]).not.toHaveTextContent('UTC')
    expect(options[1]).toHaveTextContent('America/Los_Angeles')
  })

  it('filters options when typing', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'tokyo')

    const listbox = screen.getByRole('listbox')
    const options = within(listbox).getAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('Asia/Tokyo (Tokyo)')
  })

  it('filters case-insensitively on IANA key', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'america')

    const listbox = screen.getByRole('listbox')
    const options = within(listbox).getAllByRole('option')
    expect(options).toHaveLength(2)
  })

  it('calls onChange with IANA key when option is clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <TimezoneCombobox value="UTC" onChange={onChange} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    const listbox = screen.getByRole('listbox')
    const option = within(listbox).getByText('Asia/Tokyo (Tokyo)')
    await user.click(option)

    expect(onChange).toHaveBeenCalledWith('Asia/Tokyo')
  })

  it('is disabled when disabled prop is true', () => {
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={true} />,
    )
    const input = screen.getByRole('combobox')
    expect(input).toBeDisabled()
  })

  it('does not open dropdown when disabled', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={true} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes dropdown on Escape and reverts input text', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'tok')

    expect(screen.getByRole('listbox')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveValue('UTC')
  })

  it('selects option with Enter key after arrow navigation', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <TimezoneCombobox value="UTC" onChange={onChange} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    // ArrowDown to highlight first, ArrowDown to second, Enter to select
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    // Second item is UTC (first is detected: America/New_York)
    expect(onChange).toHaveBeenCalledWith('UTC')
  })

  it('navigates with ArrowUp and wraps around', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    // ArrowUp from no highlight should wrap to last item
    await user.keyboard('{ArrowUp}')
    await user.keyboard('{Enter}')

    // Last item alphabetically is Pacific/Auckland
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes dropdown when clicking outside', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <button>outside</button>
        <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />
      </div>,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    expect(screen.getByRole('listbox')).toBeInTheDocument()

    await user.click(screen.getByText('outside'))

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    // Input should revert to display format
    expect(input).toHaveValue('UTC')
  })

  it('has correct ARIA attributes', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="America/New_York" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    expect(input).toHaveAttribute('aria-expanded', 'false')

    await user.click(input)

    expect(input).toHaveAttribute('aria-expanded', 'true')

    const listbox = screen.getByRole('listbox')
    expect(listbox).toBeInTheDocument()

    const options = within(listbox).getAllByRole('option')
    for (const option of options) {
      expect(option).toHaveAttribute('id')
    }
  })

  it('sets aria-activedescendant during keyboard navigation', async () => {
    const user = userEvent.setup()
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    await user.click(input)

    await user.keyboard('{ArrowDown}')

    const activeId = input.getAttribute('aria-activedescendant')
    expect(activeId).toBeTruthy()

    const activeOption = document.getElementById(activeId!)
    expect(activeOption).toBeInTheDocument()
    expect(activeOption).toHaveAttribute('role', 'option')
  })

  it('uses id="site-timezone" on the input', () => {
    render(
      <TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />,
    )
    const input = screen.getByRole('combobox')
    expect(input).toHaveAttribute('id', 'site-timezone')
  })
})
