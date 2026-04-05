import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type Connection,
  useNodesState,
  useEdgesState,
  type NodeTypes,
  type NodeProps,
  type ReactFlowProps,
  Handle,
  Position,
  MarkerType,
} from '@xyflow/react'
import { useSWRConfig } from 'swr'
import '@xyflow/react/dist/style.css'
import Dagre from '@dagrejs/dagre'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useAuthStore } from '@/stores/authStore'
import { fetchLabel, updateLabel } from '@/api/labels'
import { HTTPError } from '@/api/client'
import { matchesLabelSearch } from '@/components/labels/searchUtils'
import type { LabelGraphResponse } from '@/api/client'
import { computeDepths, wouldCreateCycle } from '@/components/labels/graphUtils'
import { useLabelGraph } from '@/hooks/useLabelGraph'

/* ── Types ─────────────────────────────────────────── */

interface LabelNodeData {
  label: string
  names: string[]
  postCount: number
  depth: number
}

/* ── Custom node ────────────────────────────────────── */

function LabelNode({ data }: NodeProps) {
  const d = data as unknown as LabelNodeData
  const depthColors = [
    'border-accent bg-accent/8 dark:bg-accent/20 text-accent',
    'border-amber-600 dark:border-amber-500 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-400',
    'border-emerald-600 dark:border-emerald-500 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-400',
    'border-sky-600 dark:border-sky-500 bg-sky-50 dark:bg-sky-950/30 text-sky-800 dark:text-sky-300',
    'border-violet-600 dark:border-violet-500 bg-violet-50 dark:bg-violet-900/30 text-violet-800 dark:text-violet-400',
  ]
  const style = depthColors[d.depth % depthColors.length]

  return (
    <div
      className={`rounded-lg border-2 px-4 py-2.5 shadow-sm cursor-pointer
        transition-all hover:shadow-md hover:scale-[1.04] ${style}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-border-dark !w-2 !h-2" />
      <div className="font-display text-base leading-tight">#{d.label}</div>
      {d.names.length > 0 && (
        <div className="text-xs opacity-70 mt-0.5 max-w-[140px] truncate">
          {d.names[0]}
        </div>
      )}
      <div className="text-[10px] mt-1.5 font-mono opacity-60">
        {d.postCount} {d.postCount === 1 ? 'post' : 'posts'}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-border-dark !w-2 !h-2" />
    </div>
  )
}

const nodeTypes: NodeTypes = { label: LabelNode }

/* ── Dagre layout ───────────────────────────────────── */

function layoutGraph(
  graphData: LabelGraphResponse,
  depthMap: Map<string, number>,
  isEditable: boolean,
): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 50, edgesep: 30 })

  for (const node of graphData.nodes) {
    g.setNode(node.id, { width: 160, height: 80 })
  }

  for (const edge of graphData.edges) {
    // edge.source = child, edge.target = parent
    // for dagre: parent -> child (top-down)
    g.setEdge(edge.target, edge.source)
  }

  Dagre.layout(g)

  const nodes: Node[] = graphData.nodes.map((n) => {
    const pos = g.node(n.id) as { x: number; y: number }
    return {
      id: n.id,
      type: 'label',
      position: { x: pos.x - 80, y: pos.y - 40 },
      data: {
        label: n.id,
        names: n.names,
        postCount: n.post_count,
        depth: depthMap.get(n.id) ?? 0,
      },
    }
  })

  const edgeColor = 'var(--color-border-dark)'
  const edges: Edge[] = graphData.edges.map((e) => ({
    id: `${e.target}-${e.source}`,
    source: e.target,
    target: e.source,
    animated: false,
    style: { stroke: edgeColor, strokeWidth: 2, ...(isEditable ? { cursor: 'pointer' } : {}) },
    markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor, width: 16, height: 16 },
    interactionWidth: isEditable ? 20 : 0,
  }))

  return { nodes, edges }
}

/* ── Main component ────────────────────────────────── */

export default function LabelGraphPage({ search }: { search: string }) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { mutate } = useSWRConfig()
  const initialNodes: Node[] = []
  const initialEdges: Edge[] = []
  const { data: graphData, error: graphErr, isLoading: loading, mutate: mutateGraph } = useLabelGraph()
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [mutating, setMutating] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const error = graphErr instanceof HTTPError && graphErr.response.status === 401
    ? 'Session expired. Please log in to view the graph.'
    : graphErr !== undefined
      ? 'Failed to load label graph. Please try again later.'
      : null

  const depthMap = useMemo(
    () => (graphData ? computeDepths(graphData) : new Map<string, number>()),
    [graphData],
  )

  useEffect(() => {
    if (!graphData) return
    const { nodes: n, edges: e } = layoutGraph(graphData, depthMap, !!user)
    setNodes(n)
    setEdges(e)
  }, [graphData, depthMap, setNodes, setEdges, user])

  const persistParentEdit = useCallback(async (
    childId: string,
    applyParents: (currentParents: string[]) => string[],
  ) => {
    const latestLabel = await fetchLabel(childId)
    const nextParents = applyParents(latestLabel.parents)
    await updateLabel(childId, { names: latestLabel.names, parents: nextParents })
  }, [])

  // Search highlight
  const filteredNodes = useMemo(() => {
    if (!search.trim()) return nodes
    return nodes.map((n) => {
      const d = n.data as unknown as LabelNodeData
      const match = matchesLabelSearch(d.label, d.names, search)
      return {
        ...n,
        style: match ? {} : { opacity: 0.2 },
      }
    })
  }, [nodes, search])

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      void navigate(`/labels/${node.id}`)
    },
    [navigate],
  )

  const isValidConnection = useCallback(
    (connection: { source: string | null; target: string | null }) => {
      if (graphData == null || connection.source === null || connection.target === null) return false
      if (connection.source === connection.target) return false
      // connection.source = parent node (React Flow source), connection.target = child node
      // Check if child -> parent would create a cycle
      return !wouldCreateCycle(graphData, connection.target, connection.source)
    },
    [graphData],
  )

  const onConnect = useCallback(
    async (connection: Connection) => {
      if (!graphData || mutating) return
      if (!user) return
      if (!connection.source || !connection.target) return

      // connection.source = parent (React Flow source), connection.target = child (React Flow target)
      const childId = connection.target
      const parentId = connection.source

      setMutating(true)
      setEditError(null)
      try {
        await persistParentEdit(
          childId,
          (currentParents) => [...new Set([...currentParents, parentId])],
        )
      } catch {
        setEditError('Failed to add parent relationship.')
        return
      } finally {
        setMutating(false)
      }
      await Promise.all([
        mutateGraph(),
        mutate(['labels', user.id], undefined, { revalidate: true }),
      ]).catch(() => undefined)
    },
    [graphData, mutate, user, mutating, mutateGraph, persistParentEdit],
  )

  const onEdgeClick = useCallback(
    async (_: React.MouseEvent, edge: Edge) => {
      if (!graphData || !user || mutating) return

      // React Flow edge: source = parent, target = child
      const childId = edge.target
      const parentId = edge.source

      if (!window.confirm(`Remove parent #${parentId} from #${childId}?`)) return

      setMutating(true)
      setEditError(null)
      try {
        await persistParentEdit(
          childId,
          (currentParents) => currentParents.filter((parent) => parent !== parentId),
        )
      } catch {
        setEditError('Failed to remove parent relationship.')
        return
      } finally {
        setMutating(false)
      }
      await Promise.all([
        mutateGraph(),
        mutate(['labels', user.id], undefined, { revalidate: true }),
      ]).catch(() => undefined)
    },
    [graphData, mutate, user, mutating, mutateGraph, persistParentEdit],
  )

  const interactiveFlowProps = useMemo<
    Pick<ReactFlowProps, 'isValidConnection' | 'onConnect' | 'onEdgeClick' | 'edgesReconnectable'>
  >(
    () =>
      user
        ? {
            isValidConnection,
            onConnect: (connection) => {
              void onConnect(connection)
            },
            onEdgeClick: (event, edge) => {
              void onEdgeClick(event, edge)
            },
            edgesReconnectable: true,
          }
        : { edgesReconnectable: false },
    [user, isValidConnection, onConnect, onEdgeClick],
  )

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null) {
    return (
      <div className="text-center py-24 animate-fade-in">
        <p className="text-red-600 dark:text-red-400">{error}</p>
      </div>
    )
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="text-center py-24 animate-fade-in">
        <p className="font-display text-2xl text-muted italic">No labels yet</p>
        <p className="text-sm text-muted mt-2">Define labels in labels.toml to see the graph.</p>
      </div>
    )
  }

  return (
    <div className="-mx-6">
      {(mutating || editError !== null) && (
        <div className="px-6 pb-3 flex items-center gap-3">
          {mutating && (
            <div className="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
          )}
          {editError !== null && (
            <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 px-3 py-1.5 rounded-lg">
              {editError}
            </div>
          )}
        </div>
      )}

      <div style={{ height: 'calc(100vh - 220px)' }}>
        <ReactFlow
          nodes={filteredNodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          {...interactiveFlowProps}
          connectOnClick={false}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={2}
        >
          <Background color="var(--color-border)" gap={20} size={1} />
          <Controls
            className="!bg-paper !border-border !shadow-sm [&>button]:!bg-paper [&>button]:!border-border [&>button]:!text-muted [&>button:hover]:!bg-paper-warm"
          />
          <MiniMap
            nodeColor="var(--color-border-dark)"
            maskColor="var(--color-minimap-mask)"
            className="!bg-paper !border-border !shadow-sm !rounded-lg"
          />
        </ReactFlow>
      </div>
    </div>
  )
}
