import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

import LabelChip from '../LabelChip'

function renderChip(props: { labelId: string; clickable?: boolean }) {
  return render(
    <MemoryRouter>
      <LabelChip {...props} />
    </MemoryRouter>,
  )
}

describe('LabelChip', () => {
  it('renders label with hash prefix', () => {
    renderChip({ labelId: 'swe' })
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })

  it('renders as link by default', () => {
    renderChip({ labelId: 'swe' })
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/labels/swe')
  })

  it('renders as span when not clickable', () => {
    renderChip({ labelId: 'swe', clickable: false })
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('#swe').tagName).toBe('SPAN')
  })

  it('is wrapped in React.memo', async () => {
    const { default: LabelChipModule } = await import('../LabelChip')
    expect((LabelChipModule as unknown as { $$typeof: symbol }).$$typeof).toBe(
      Symbol.for('react.memo'),
    )
  })

  it('stops event propagation on click', async () => {
    const parentClick = vi.fn()
    render(
      <MemoryRouter>
        <div onClick={parentClick}>
          <LabelChip labelId="swe" />
        </div>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('link'))
    expect(parentClick).not.toHaveBeenCalled()
  })
})
