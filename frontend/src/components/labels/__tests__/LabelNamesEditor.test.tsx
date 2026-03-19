import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import LabelNamesEditor from '../LabelNamesEditor'

describe('LabelNamesEditor', () => {
  it('is wrapped in React.memo for re-render optimization', () => {
    expect(LabelNamesEditor).toHaveProperty('$$typeof', Symbol.for('react.memo'))
  })

  it('renders existing names as tags', () => {
    render(<LabelNamesEditor names={['python', 'py']} onNamesChange={vi.fn()} disabled={false} />)
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByText('py')).toBeInTheDocument()
  })

  it('adds a new name on button click', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['existing']} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'new-name')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).toHaveBeenCalledWith(['existing', 'new-name'])
  })

  it('adds a new name on Enter key', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'entered{Enter}')

    expect(onNamesChange).toHaveBeenCalledWith(['entered'])
  })

  it('removes a name when remove button is clicked', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['keep', 'remove']} onNamesChange={onNamesChange} disabled={false} />)

    await user.click(screen.getByLabelText('Remove name "remove"'))

    expect(onNamesChange).toHaveBeenCalledWith(['keep'])
  })

  it('removes only the clicked duplicate name', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(
      <LabelNamesEditor
        names={['duplicate', 'duplicate', 'keep']}
        onNamesChange={onNamesChange}
        disabled={false}
      />,
    )

    await user.click(screen.getAllByLabelText('Remove name "duplicate"')[0]!)

    expect(onNamesChange).toHaveBeenCalledWith(['duplicate', 'keep'])
  })

  it('prevents adding duplicate names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['existing']} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'existing')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).not.toHaveBeenCalled()
  })

  it('disables all controls when disabled is true', () => {
    render(<LabelNamesEditor names={['test']} onNamesChange={vi.fn()} disabled={true} />)

    expect(screen.getByPlaceholderText('Add a display name...')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
    expect(screen.getByLabelText('Remove name "test"')).toBeDisabled()
  })

  it('trims whitespace from new names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), '  spaced  ')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).toHaveBeenCalledWith(['spaced'])
  })

  it('does not add empty names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).not.toHaveBeenCalled()
  })
})
