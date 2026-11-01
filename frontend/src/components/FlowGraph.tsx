import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import type { AutomationDetail, NodeStat, Step } from '../api'
import { duration, pct, usd } from '../format'

export type HeatMetric = 'latency' | 'cost' | 'failure'

type HubData = {
  label: string
  meta: string
  className: string
  style?: React.CSSProperties
}

// Heat ramp from cool to hot; the border carries the colour so the label stays readable.
const RAMP = [
  { bg: 'rgba(9, 63, 82, 0.45)', border: 'rgba(101, 167, 194, 0.22)' },
  { bg: 'rgba(33, 106, 133, 0.35)', border: '#216A85' },
  { bg: 'rgba(33, 106, 133, 0.6)', border: '#3E88A6' },
  { bg: 'rgba(101, 167, 194, 0.42)', border: '#65A7C2' },
  { bg: 'rgba(199, 229, 242, 0.32)', border: '#C7E5F2' },
]
export const RAMP_COLORS = RAMP.map((r) => r.border)

function HubNode({ data }: NodeProps<Node<HubData>>) {
  return (
    <div className={`hub-node ${data.className}`} style={data.style} title={data.label}>
      <Handle type="target" position={Position.Top} />
      <div className="title">
        <span className="dot" />
        <span>{data.label}</span>
      </div>
      <div className="meta">{data.meta}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
const nodeTypes = { hub: HubNode }

type Props = {
  automation: AutomationDetail
  /** run replay: steps of one run */
  steps?: Step[]
  runActive?: boolean
  /** heatmap: averages per node */
  heat?: { metric: HeatMetric; nodes: Record<string, NodeStat> }
  selected?: string | null
  onSelect?: (nodeId: string) => void
}

function heatValue(stat: NodeStat | undefined, metric: HeatMetric): number | null {
  if (!stat || stat.human) return null
  if (metric === 'latency') return stat.avg_ms
  if (metric === 'cost') return stat.avg_cost_usd
  return stat.failure_rate
}

function heatLabel(stat: NodeStat | undefined, metric: HeatMetric): string {
  if (!stat) return 'no runs yet'
  if (stat.human) return `human · ${duration(stat.avg_ms)}`
  if (metric === 'latency') return duration(stat.avg_ms)
  if (metric === 'cost') return usd(stat.avg_cost_usd)
  return `${pct(stat.failure_rate)} failed`
}

export function FlowGraph({ automation, steps, runActive, heat, selected, onSelect, compact }: Props & { compact?: boolean }) {
  const { nodes, edges } = useMemo(() => {
    const byNode = new Map((steps ?? []).map((s) => [s.node_id, s]))
    const maxHeat = heat
      ? Math.max(0, ...automation.graph.nodes.map((n) => heatValue(heat.nodes[n.id], heat.metric) ?? 0))
      : 0

    const nodes: Node<HubData>[] = automation.graph.nodes.map((n) => {
      let className = ''
      let meta = ''
      let style: React.CSSProperties | undefined
      if (heat) {
        const stat = heat.nodes[n.id]
        const value = heatValue(stat, heat.metric)
        meta = heatLabel(stat, heat.metric)
        if (stat?.human) className = 'human-heat'
        else if (value !== null && maxHeat > 0) {
          const level = Math.min(4, Math.round((value / maxHeat) * 4))
          style = { background: RAMP[level].bg, borderColor: RAMP[level].border }
          if (level === 4) style.boxShadow = '0 0 0 4px rgba(199, 229, 242, 0.16), 0 0 34px rgba(101, 167, 194, 0.6)'
        } else className = 'idle'
      } else if (steps) {
        const step = byNode.get(n.id)
        if (step) {
          className = step.status
          meta =
            step.status === 'waiting'
              ? 'waiting for a person'
              : step.status === 'skipped'
                ? 'skipped'
                : `${duration(step.duration_ms)}${step.cost_usd ? ` · ${usd(step.cost_usd)}` : ''}${step.attempts > 1 ? ` · ${step.attempts} tries` : ''}`
        } else {
          className = 'idle'
          meta = runActive ? 'pending' : 'not reached'
        }
      }
      if (selected === n.id) className += ' selected'
      return { id: n.id, type: 'hub', position: n.position, data: { label: n.data.label, meta, className, style } }
    })

    // an edge counts as travelled when its target ran straight after its source
    const edges: Edge[] = automation.graph.edges.map((e) => {
      const from = byNode.get(e.source)
      const to = byNode.get(e.target)
      const travelled = !!(from && to && to.position === from.position + 1)
      const color = travelled ? (to?.status === 'waiting' ? '#E9A84C' : '#65A7C2') : 'rgba(101, 167, 194, 0.25)'
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: travelled && !!runActive,
        style: { stroke: color, strokeWidth: travelled ? 2 : 1.5, strokeDasharray: steps && !travelled ? '5 5' : undefined },
        labelStyle: { fill: travelled ? '#C7E5F2' : '#7598AA', fontFamily: 'JetBrains Mono', fontSize: 11 },
        labelBgStyle: { fill: '#042933' },
      }
    })
    return { nodes, edges }
  }, [automation, steps, runActive, heat, selected])

  return (
    <div className={`graph ${compact ? 'compact' : ''}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.06, maxZoom: 1.1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, node) => onSelect?.(node.id)}
        minZoom={0.3}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="rgba(199, 229, 242, 0.09)" gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
