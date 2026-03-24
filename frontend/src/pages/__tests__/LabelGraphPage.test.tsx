import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useState } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, LabelGraphResponse } from '@/api/client'
import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
})

const mockFetchLabelGraph = vi.fn()
const mockFetchLabel = vi.fn()
const mockUpdateLabel = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabelGraph: (...args: unknown[]) => mockFetchLabelGraph(...args) as unknown,
  fetchLabel: (...args: unknown[]) => mockFetchLabel(...args) as unknown,
  updateLabel: (...args: unknown[]) => mockUpdateLabel(...args) as unknown,
}))

// Capture interactive props from ReactFlow for testing callbacks
interface CapturedFlowProps {
  onNodeClick?: ((event: React.MouseEvent, node: { id: string }) => void) | undefined
  onConnect?: ((connection: { source: string; target: string; sourceHandle: null; targetHandle: null }) => void) | undefined
  onEdgeClick?: ((event: React.MouseEvent, edge: { id: string; source: string; target: string }) => void) | undefined
  isValidConnection?: ((connection: { source: string | null; target: string | null }) => boolean) | undefined
  backgroundColor?: string | undefined
  minimapNodeColor?: string | undefined
  minimapMaskColor?: string | undefined
}

let capturedFlowProps: CapturedFlowProps = {}

vi.mock('@xyflow/react', () => {
  // Use React.useState so that setNodes/setEdges trigger re-renders
  const useNodesState = (initial: unknown[]) => {
    const [nodes, setNodes] = useState(initial)
    return [nodes, setNodes, vi.fn()]
  }
  const useEdgesState = (initial: unknown[]) => {
    const [edges, setEdges] = useState(initial)
    return [edges, setEdges, vi.fn()]
  }
  return {
    ReactFlow: (props: {
      nodes?: Array<{ id: string; style?: { opacity?: number }; data?: { label?: string; names?: string[] } }>
      onNodeClick?: CapturedFlowProps['onNodeClick']
      onConnect?: CapturedFlowProps['onConnect']
      onEdgeClick?: CapturedFlowProps['onEdgeClick']
      isValidConnection?: CapturedFlowProps['isValidConnection']
      children?: React.ReactNode
    }) => {
      capturedFlowProps = {
        onNodeClick: props.onNodeClick,
        onConnect: props.onConnect,
        onEdgeClick: props.onEdgeClick,
        isValidConnection: props.isValidConnection,
      }
      return (
        <div data-testid="react-flow">
          {Array.isArray(props.nodes) && props.nodes.map((n) => (
            <div
              key={n.id}
              data-testid={`node-${n.id}`}
              data-opacity={n.style?.opacity}
            >
              {n.data?.label}
            </div>
          ))}
          {props.children}
        </div>
      )
    },
    Background: (props: { color?: string }) => {
      capturedFlowProps.backgroundColor = props.color
      return null
    },
    Controls: () => null,
    MiniMap: (props: { nodeColor?: string; maskColor?: string }) => {
      capturedFlowProps.minimapNodeColor = props.nodeColor
      capturedFlowProps.minimapMaskColor = props.maskColor
      return null
    },
    Handle: () => null,
    Position: { Top: 'top', Bottom: 'bottom' },
    MarkerType: { ArrowClosed: 'arrowclosed' },
    useNodesState,
    useEdgesState,
  }
})

vi.mock('@dagrejs/dagre', () => {
  function MockGraph() {
    return {
      setDefaultEdgeLabel: vi.fn().mockReturnThis(),
      setGraph: vi.fn(),
      setNode: vi.fn(),
      setEdge: vi.fn(),
      node: () => ({ x: 100, y: 100 }),
    }
  }
  return {
    default: {
      graphlib: { Graph: MockGraph },
      layout: vi.fn(),
    },
  }
})

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import LabelGraphPage from '../LabelGraphPage'

const graphData: LabelGraphResponse = {
  nodes: [
    { id: 'cs', names: ['computer science'], post_count: 10 },
    { id: 'swe', names: ['software engineering'], post_count: 5 },
    { id: 'math', names: ['mathematics'], post_count: 3 },
  ],
  edges: [{ source: 'swe', target: 'cs' }],
}

function renderGraph(search = '') {
  return render(
    <MemoryRouter>
      <LabelGraphPage search={search} />
    </MemoryRouter>,
  )
}

describe('LabelGraphPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedFlowProps = {}
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
  })

  it('shows spinner while loading', () => {
    mockFetchLabelGraph.mockReturnValue(new Promise(() => {}))
    renderGraph()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows error message', async () => {
    mockFetchLabelGraph.mockRejectedValue(new Error('Network'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderGraph()

    await waitFor(() => {
      expect(screen.getByText('Failed to load label graph. Please try again later.')).toBeInTheDocument()
    })
    consoleSpy.mockRestore()
  })

  it('shows "No labels yet" when empty', async () => {
    mockFetchLabelGraph.mockResolvedValue({ nodes: [], edges: [] })
    renderGraph()

    await waitFor(() => {
      expect(screen.getByText('No labels yet')).toBeInTheDocument()
    })
  })

  it('renders the graph with nodes', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument()
    })
  })

  it('shows 401 error as session expired', async () => {
    mockFetchLabelGraph.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    renderGraph()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in to view the graph.')).toBeInTheDocument()
    })
  })

  it('renders without edit controls when unauthenticated', async () => {
    mockUser = null
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument()
    })
  })

  it('keeps the graph background separate from the minimap overlay colors', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument()
    })

    expect(capturedFlowProps.backgroundColor).toBe('var(--color-border)')
    expect(capturedFlowProps.minimapNodeColor).toBe('var(--color-border-dark)')
    expect(capturedFlowProps.minimapMaskColor).toBe('var(--color-minimap-mask)')
  })

  it('search dims non-matching nodes', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph('math')

    await waitFor(() => {
      expect(screen.getByTestId('node-math')).toBeInTheDocument()
    })

    // math node should not have opacity set (matches search)
    const mathNode = screen.getByTestId('node-math')
    expect(mathNode.dataset['opacity']).toBeUndefined()

    // cs node should have reduced opacity (does not match search)
    const csNode = screen.getByTestId('node-cs')
    expect(csNode.dataset['opacity']).toBe('0.2')
  })

  it('search matches by label name (alias)', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph('software')

    await waitFor(() => {
      expect(screen.getByTestId('node-swe')).toBeInTheDocument()
    })

    // swe node matches via its name "software engineering"
    const sweNode = screen.getByTestId('node-swe')
    expect(sweNode.dataset['opacity']).toBeUndefined()

    // cs should be dimmed
    const csNode = screen.getByTestId('node-cs')
    expect(csNode.dataset['opacity']).toBe('0.2')
  })

  it('onNodeClick navigates to label page', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onNodeClick).toBeDefined()
    })

    act(() => {
      capturedFlowProps.onNodeClick!(new MouseEvent('click') as unknown as React.MouseEvent, { id: 'cs' })
    })

    expect(mockNavigate).toHaveBeenCalledWith('/labels/cs')
  })

  it('isValidConnection rejects self-connection', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.isValidConnection).toBeDefined()
    })

    expect(capturedFlowProps.isValidConnection!({ source: 'cs', target: 'cs' })).toBe(false)
  })

  it('isValidConnection rejects null values', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.isValidConnection).toBeDefined()
    })

    expect(capturedFlowProps.isValidConnection!({ source: null, target: 'cs' })).toBe(false)
    expect(capturedFlowProps.isValidConnection!({ source: 'cs', target: null })).toBe(false)
  })

  it('isValidConnection rejects cycle-creating connections', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.isValidConnection).toBeDefined()
    })

    // swe -> cs edge exists. Adding cs -> swe would create a cycle.
    // source = parent, target = child in ReactFlow terms
    // wouldCreateCycle(graphData, child=cs, parent=swe) should detect the cycle
    expect(capturedFlowProps.isValidConnection!({ source: 'swe', target: 'cs' })).toBe(false)
  })

  it('isValidConnection accepts valid connections', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.isValidConnection).toBeDefined()
    })

    // math -> cs (cs becomes parent of math) — no cycle
    expect(capturedFlowProps.isValidConnection!({ source: 'cs', target: 'math' })).toBe(true)
  })

  it('onConnect adds parent relationship', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    mockFetchLabel.mockResolvedValue({ id: 'math', names: ['mathematics'], parents: [], children: [], post_count: 3, is_implicit: false })
    mockUpdateLabel.mockResolvedValue({})
    // After update, refetch returns updated graph
    mockFetchLabelGraph.mockResolvedValueOnce(graphData).mockResolvedValueOnce({
      ...graphData,
      edges: [...graphData.edges, { source: 'math', target: 'cs' }],
    })

    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onConnect).toBeDefined()
    })

    // Trigger connect: source = parent (cs), target = child (math)
    await act(async () => {
      await (capturedFlowProps.onConnect!({
        source: 'cs',
        target: 'math',
        sourceHandle: null,
        targetHandle: null,
      }) as unknown as Promise<void>)
    })

    expect(mockFetchLabel).toHaveBeenCalledWith('math')
    expect(mockUpdateLabel).toHaveBeenCalledWith('math', { names: ['mathematics'], parents: ['cs'] })
  })

  it('onConnect shows error on failure', async () => {
    mockFetchLabelGraph.mockResolvedValue(graphData)
    mockFetchLabel.mockRejectedValue(new Error('Network error'))

    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onConnect).toBeDefined()
    })

    await act(async () => {
      await (capturedFlowProps.onConnect!({
        source: 'cs',
        target: 'math',
        sourceHandle: null,
        targetHandle: null,
      }) as unknown as Promise<void>)
    })

    await waitFor(() => {
      expect(screen.getByText('Failed to add parent relationship.')).toBeInTheDocument()
    })
  })

  it('onConnect is no-op when unauthenticated', async () => {
    mockUser = null
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument()
    })

    // No onConnect should be set when unauthenticated
    expect(capturedFlowProps.onConnect).toBeUndefined()
  })

  it('onEdgeClick removes parent relationship on confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockFetchLabelGraph.mockResolvedValue(graphData)
    mockFetchLabel.mockResolvedValue({
      id: 'swe', names: ['software engineering'], parents: ['cs'], children: [], post_count: 5, is_implicit: false,
    })
    mockUpdateLabel.mockResolvedValue({})
    // After removal, refetch returns graph without the edge
    mockFetchLabelGraph.mockResolvedValueOnce(graphData).mockResolvedValueOnce({
      ...graphData,
      edges: [],
    })

    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onEdgeClick).toBeDefined()
    })

    // Edge: source = parent (cs), target = child (swe) in ReactFlow
    await act(async () => {
      await (capturedFlowProps.onEdgeClick!(
        new MouseEvent('click') as unknown as React.MouseEvent,
        { id: 'cs-swe', source: 'cs', target: 'swe' },
      ) as unknown as Promise<void>)
    })

    expect(window.confirm).toHaveBeenCalledWith('Remove parent #cs from #swe?')
    expect(mockFetchLabel).toHaveBeenCalledWith('swe')
    expect(mockUpdateLabel).toHaveBeenCalledWith('swe', { names: ['software engineering'], parents: [] })
  })

  it('onEdgeClick does nothing when confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    mockFetchLabelGraph.mockResolvedValue(graphData)

    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onEdgeClick).toBeDefined()
    })

    await act(async () => {
      await (capturedFlowProps.onEdgeClick!(
        new MouseEvent('click') as unknown as React.MouseEvent,
        { id: 'cs-swe', source: 'cs', target: 'swe' },
      ) as unknown as Promise<void>)
    })

    expect(mockFetchLabel).not.toHaveBeenCalled()
    expect(mockUpdateLabel).not.toHaveBeenCalled()
  })

  it('onEdgeClick shows error on failure', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockFetchLabelGraph.mockResolvedValue(graphData)
    mockFetchLabel.mockRejectedValue(new Error('Network error'))

    renderGraph()

    await waitFor(() => {
      expect(capturedFlowProps.onEdgeClick).toBeDefined()
    })

    await act(async () => {
      await (capturedFlowProps.onEdgeClick!(
        new MouseEvent('click') as unknown as React.MouseEvent,
        { id: 'cs-swe', source: 'cs', target: 'swe' },
      ) as unknown as Promise<void>)
    })

    await waitFor(() => {
      expect(screen.getByText('Failed to remove parent relationship.')).toBeInTheDocument()
    })
  })

  it('onEdgeClick is no-op when unauthenticated', async () => {
    mockUser = null
    mockFetchLabelGraph.mockResolvedValue(graphData)
    renderGraph()

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument()
    })

    // No onEdgeClick should be set when unauthenticated
    expect(capturedFlowProps.onEdgeClick).toBeUndefined()
  })
})
