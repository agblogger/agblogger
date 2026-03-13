import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchLabels, createLabel } from '@/api/labels'
import { HTTPError } from '@/test/MockHTTPError'
import type { LabelResponse } from '@/api/client'

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn(),
  createLabel: vi.fn(),
}))

vi.mock('@/api/client', async () => {
  const { HTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError }
})

import LabelInput from '../LabelInput'

const mockFetchLabels = vi.mocked(fetchLabels)
const mockCreateLabel = vi.mocked(createLabel)

const sampleLabels: LabelResponse[] = [
  { id: 'swe', names: ['software engineering'], is_implicit: false, parents: [], children: [], post_count: 3 },
  { id: 'math', names: ['mathematics'], is_implicit: false, parents: [], children: [], post_count: 1 },
  { id: 'cs', names: ['computer science'], is_implicit: false, parents: [], children: ['swe'], post_count: 5 },
]

async function renderLabelInput(
  props: { value?: string[]; onChange?: (labels: string[]) => void; disabled?: boolean } = {},
) {
  const onChange = props.onChange ?? vi.fn<(labels: string[]) => void>()
  const result = render(
    <LabelInput value={props.value ?? []} onChange={onChange} {...(props.disabled != null && { disabled: props.disabled })} />,
  )
  // Flush microtasks from the initial fetchLabels() effect
  await act(async () => {})
  return { ...result, onChange }
}

describe('LabelInput', () => {
  beforeEach(() => {
    mockFetchLabels.mockReset()
    mockCreateLabel.mockReset()
    mockFetchLabels.mockResolvedValue(sampleLabels)
  })

  it('loads and shows labels in dropdown on focus', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.getByText('#math')).toBeInTheDocument()
    expect(screen.getByText('#cs')).toBeInTheDocument()
  })

  it('filters labels by query', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'sw')

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.queryByText('#math')).not.toBeInTheDocument()
  })

  it('filters labels by name case-insensitively', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'Software')

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.queryByText('#math')).not.toBeInTheDocument()
    expect(screen.queryByText('#cs')).not.toBeInTheDocument()
  })

  it('selects label on click', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.click(screen.getByText('#swe'))

    expect(onChange).toHaveBeenCalledWith(['swe'])
  })

  it('excludes already-selected labels from dropdown', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ value: ['swe'], onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#math')).toBeInTheDocument()
    })
    // swe is already selected, so shouldn't be in dropdown
    expect(screen.queryByRole('option', { name: /#swe/ })).not.toBeInTheDocument()
  })

  it('renders selected label chips with remove buttons', async () => {
    const onChange = vi.fn()
    await renderLabelInput({ value: ['swe', 'math'], onChange })

    expect(screen.getByText('#swe')).toBeInTheDocument()
    expect(screen.getByText('#math')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /remove label/i }).length).toBe(2)
  })

  it('removes label on chip X click', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ value: ['swe', 'math'], onChange })

    await user.click(screen.getByLabelText('Remove label swe'))

    expect(onChange).toHaveBeenCalledWith(['math'])
  })

  it('removes last label on Backspace when input is empty', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ value: ['swe', 'math'], onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.keyboard('{Backspace}')

    expect(onChange).toHaveBeenCalledWith(['swe'])
  })

  it('selects first label on Enter when dropdown is open', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.keyboard('{ArrowDown}{Enter}')

    expect(onChange).toHaveBeenCalledWith(['swe'])
  })

  it('navigates with ArrowDown/ArrowUp and selects with Enter', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    // ArrowDown to open and select first, then again to go to second
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    // Second label should be selected (math)
    expect(onChange).toHaveBeenCalledWith(['math'])
  })

  it('closes dropdown on Escape', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('shows "Create #label" option for new label', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'newlabel')

    await waitFor(() => {
      expect(screen.getByText('Create #newlabel')).toBeInTheDocument()
    })
  })

  it('creates a new label via Enter', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const newLabel: LabelResponse = {
      id: 'newlabel', names: ['newlabel'], is_implicit: false,
      parents: [], children: [], post_count: 0,
    }
    mockCreateLabel.mockResolvedValueOnce(newLabel)
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'newlabel')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(mockCreateLabel).toHaveBeenCalledWith({ id: 'newlabel' })
    })
    expect(onChange).toHaveBeenCalledWith(['newlabel'])
  })

  it('handles 409 on create by adding existing label', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    mockCreateLabel.mockRejectedValueOnce(
      new (HTTPError as unknown as new (s: number) => Error)(409),
    )
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    // Use a label that doesn't match any existing ID exactly
    await user.type(input, 'physics')

    await waitFor(() => {
      expect(screen.getByText('Create #physics')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Create #physics'))

    // On 409, the label is added as if it already existed
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(['physics'])
    })
  })

  it('shows error on failed create', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    mockCreateLabel.mockRejectedValueOnce(new Error('Network'))
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'badlabel')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText('Failed to load labels. Type to create new ones.')).toBeInTheDocument()
    })
  })

  it('shows load error when fetch fails', async () => {
    mockFetchLabels.mockReset()
    mockFetchLabels.mockRejectedValueOnce(new Error('Network error'))

    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    await waitFor(() => {
      expect(screen.getByText('Failed to load labels. Type to create new ones.')).toBeInTheDocument()
    })
  })

  it('hides remove buttons when disabled', async () => {
    const onChange = vi.fn()
    await renderLabelInput({ value: ['swe'], onChange, disabled: true })

    expect(screen.getByText('#swe')).toBeInTheDocument()
    expect(screen.queryByLabelText('Remove label swe')).not.toBeInTheDocument()
  })

  it('disables input when disabled prop is true', async () => {
    const onChange = vi.fn()
    await renderLabelInput({ onChange, disabled: true })

    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('shows primary name next to label ID in dropdown', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })
  })

  it('shows validation error on 422 create failure', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const body = JSON.stringify({ detail: [{ msg: "String should match pattern '^[a-z0-9][a-z0-9-]*'" }] })
    mockCreateLabel.mockRejectedValueOnce(
      new (HTTPError as unknown as new (s: number, b: string) => Error)(422, body),
    )
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'BAD LABEL')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText("String should match pattern '^[a-z0-9][a-z0-9-]*'")).toBeInTheDocument()
    })
    // Should NOT show the generic load error
    expect(screen.queryByText('Failed to load labels. Type to create new ones.')).not.toBeInTheDocument()
  })

  it('clears validation error when typing new query', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const body = JSON.stringify({ detail: [{ msg: 'validation error' }] })
    mockCreateLabel.mockRejectedValueOnce(
      new (HTTPError as unknown as new (s: number, b: string) => Error)(422, body),
    )
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'badlabel')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText('validation error')).toBeInTheDocument()
    })

    // Typing again should clear the validation error
    await user.type(input, 'x')
    expect(screen.queryByText('validation error')).not.toBeInTheDocument()
  })

  it('shows extracted message from 422 detail with field/message format', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const body = JSON.stringify({
      detail: [{ field: 'id', message: 'Label ID must be lowercase alphanumeric' }],
    })
    mockCreateLabel.mockRejectedValueOnce(
      new (HTTPError as unknown as new (s: number, b: string) => Error)(422, body),
    )
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'BAD LABEL')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(
        screen.getByText('Id: Label ID must be lowercase alphanumeric'),
      ).toBeInTheDocument()
    })
  })

  it('shows extracted message from 422 detail string', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const body = JSON.stringify({ detail: 'ID must be lowercase' })
    mockCreateLabel.mockRejectedValueOnce(
      new (HTTPError as unknown as new (s: number, b: string) => Error)(422, body),
    )
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, 'BAD')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText('ID must be lowercase')).toBeInTheDocument()
    })
  })

  it('strips leading # from user input when creating label', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const newLabel: LabelResponse = {
      id: 'abba', names: ['abba'], is_implicit: false,
      parents: [], children: [], post_count: 0,
    }
    mockCreateLabel.mockResolvedValueOnce(newLabel)
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.type(input, '#abba')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(mockCreateLabel).toHaveBeenCalledWith({ id: 'abba' })
    })
    expect(onChange).toHaveBeenCalledWith(['abba'])
  })

  it('ArrowUp wraps around to last item', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderLabelInput({ onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    // ArrowDown to open, then ArrowUp should wrap to last
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{ArrowUp}')
    await user.keyboard('{Enter}')

    // Last item should be selected (cs)
    expect(onChange).toHaveBeenCalledWith(['cs'])
  })
})
