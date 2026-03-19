import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import LabelParentsSelector from '../LabelParentsSelector'
import type { LabelResponse } from '@/api/client'

const sampleLabels: LabelResponse[] = [
  { id: 'python', names: ['programming'], is_implicit: false, parents: [], children: [], post_count: 5 },
  { id: 'web', names: [], is_implicit: false, parents: [], children: [], post_count: 3 },
  { id: 'async', names: ['async', 'asynchronous'], is_implicit: false, parents: [], children: [], post_count: 1 },
]

describe('LabelParentsSelector', () => {
  it('is wrapped in React.memo for re-render optimization', () => {
    expect(LabelParentsSelector).toHaveProperty('$$typeof', Symbol.for('react.memo'))
  })

  it('renders available parent labels with checkboxes', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    expect(screen.getByText('#python')).toBeInTheDocument()
    expect(screen.getByText('#web')).toBeInTheDocument()
    expect(screen.getByText('#async')).toBeInTheDocument()
    expect(screen.getByText('(programming)')).toBeInTheDocument()
    expect(screen.getByText('(async, asynchronous)')).toBeInTheDocument()
  })

  it('checks already-selected parents', () => {
    render(
      <LabelParentsSelector
        parents={['python']}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[0]).toBeChecked() // python
    expect(checkboxes[1]).not.toBeChecked() // web
  })

  it('calls onParentsChange with added parent on check', async () => {
    const onParentsChange = vi.fn()
    const user = userEvent.setup()
    render(
      <LabelParentsSelector
        parents={['python']}
        onParentsChange={onParentsChange}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    await user.click(screen.getAllByRole('checkbox')[1]!) // check 'web'

    expect(onParentsChange).toHaveBeenCalledWith(['python', 'web'])
  })

  it('calls onParentsChange with removed parent on uncheck', async () => {
    const onParentsChange = vi.fn()
    const user = userEvent.setup()
    render(
      <LabelParentsSelector
        parents={['python', 'web']}
        onParentsChange={onParentsChange}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    await user.click(screen.getAllByRole('checkbox')[0]!) // uncheck 'python'

    expect(onParentsChange).toHaveBeenCalledWith(['web'])
  })

  it('shows empty message when no parents available', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={[]}
        disabled={false}
      />
    )

    expect(screen.getByText('No other labels available as parents.')).toBeInTheDocument()
  })

  it('disables all checkboxes when disabled is true', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={true}
      />
    )

    screen.getAllByRole('checkbox').forEach((cb) => {
      expect(cb).toBeDisabled()
    })
  })

  it('does not render hint text when hint is omitted', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
      />
    )
    // The only text content should be labels and section header, no hint paragraph
    expect(screen.queryByText(/excluded/i)).not.toBeInTheDocument()
    // Verify no extra paragraph with text-muted mt-2 class exists beyond the empty-state message
  })

  it('renders hint text when provided', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
        hint="Descendants excluded to prevent cycles."
      />
    )

    expect(screen.getByText('Descendants excluded to prevent cycles.')).toBeInTheDocument()
  })
})
