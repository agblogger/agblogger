import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import DateRangePicker from '../DateRangePicker'
import type { DateRange } from '@/hooks/useAnalyticsDashboard'

function renderPicker(value: DateRange, onChange = vi.fn(), disabled = false) {
  return render(<DateRangePicker value={value} onChange={onChange} disabled={disabled} />)
}

describe('DateRangePicker', () => {
  it('renders preset buttons and date inputs', () => {
    renderPicker('7d')
    expect(screen.getByRole('button', { name: '7d' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '30d' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '90d' })).toBeInTheDocument()
    expect(screen.getByLabelText('Start date')).toBeInTheDocument()
    expect(screen.getByLabelText('End date')).toBeInTheDocument()
  })

  it('highlights the active preset', () => {
    renderPicker('30d')
    const active = screen.getByRole('button', { name: '30d' })
    expect(active).toHaveClass('bg-accent')
    expect(active).toHaveClass('text-white')
    // Others should not be highlighted
    expect(screen.getByRole('button', { name: '7d' })).not.toHaveClass('bg-accent')
    expect(screen.getByRole('button', { name: '90d' })).not.toHaveClass('bg-accent')
  })

  it('does not highlight any preset when custom range is active', () => {
    renderPicker({ start: '2024-01-01', end: '2024-01-31' })
    expect(screen.getByRole('button', { name: '7d' })).not.toHaveClass('bg-accent')
    expect(screen.getByRole('button', { name: '30d' })).not.toHaveClass('bg-accent')
    expect(screen.getByRole('button', { name: '90d' })).not.toHaveClass('bg-accent')
  })

  it('calls onChange with preset string on preset click', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderPicker('7d', onChange)
    await user.click(screen.getByRole('button', { name: '30d' }))
    expect(onChange).toHaveBeenCalledWith('30d')
  })

  it('calls onChange with CustomDateRange when start date changes', () => {
    const onChange = vi.fn()
    renderPicker({ start: '2024-01-01', end: '2024-01-31' }, onChange)
    const startInput = screen.getByLabelText('Start date')
    fireEvent.change(startInput, { target: { value: '2024-01-10' } })
    // onChange called with updated start
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ start: '2024-01-10', end: '2024-01-31' }),
    )
  })

  it('disables all controls when disabled=true', () => {
    renderPicker('7d', vi.fn(), true)
    expect(screen.getByRole('button', { name: '7d' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '30d' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '90d' })).toBeDisabled()
    expect(screen.getByLabelText('Start date')).toBeDisabled()
    expect(screen.getByLabelText('End date')).toBeDisabled()
  })

  it('shows validation error when start > end', () => {
    renderPicker({ start: '2024-03-01', end: '2024-01-01' })
    expect(screen.getByText('Start date must be before end date')).toBeInTheDocument()
  })

  it('does not show validation error when start <= end', () => {
    renderPicker({ start: '2024-01-01', end: '2024-03-01' })
    expect(screen.queryByText('Start date must be before end date')).not.toBeInTheDocument()
  })

  it('shows current custom date values in inputs', () => {
    renderPicker({ start: '2024-02-01', end: '2024-02-28' })
    expect(screen.getByLabelText('Start date')).toHaveValue('2024-02-01')
    expect(screen.getByLabelText('End date')).toHaveValue('2024-02-28')
  })
})
