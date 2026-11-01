import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Live, NodeStat } from '../api'
import { duration, usd } from '../format'
import { CHANNEL } from '../plain'
import { useTech } from '../tech'
import { Avatar } from './ui'

/**
 * The Lead Handler drawn for a business owner: the same pipeline as the technical graph,
 * grouped into steps an owner recognises. Customers being answered right now sit on the
 * step they're at, so the canvas is a live view of the assistant at work.
 */

// which engine steps each business step stands for
const GROUPS: Record<string, string[]> = {
  reads: ['intake', 'classify'],
  knows: ['retrieve', 'qualify'],
  writes: ['draft'],
  checks: ['score', 'revise'],
  ask: ['translate', 'approval'],
  send: ['send'],
  saved: ['save_lead'],
}
const BIZ_OF: Record<string, string> = Object.fromEntries(Object.entries(GROUPS).flatMap(([b, ids]) => ids.map((id) => [id, b])))

type BizData = {
  title: string; sub: string; icon: string; kind?: 'entry' | 'send' | 'ask'; iconColor?: string
  people: { run_id: string; name: string }[]; badge?: number; techLine?: string
}

function BizNode({ data }: NodeProps<Node<BizData>>) {
  const busy = data.people.length > 0
  return (
    <div className={`biz-node ${data.kind ?? ''} ${busy ? 'busy glow' : ''}`} title={busy ? `Working on: ${data.people.map((p) => p.name).join(', ')}` : data.title}>
      <Handle type="target" position={Position.Left} />
      {data.badge ? <span className="badge">{data.badge}</span> : null}
      {busy && (
        <span className="avs">{data.people.slice(0, 3).map((p) => <Avatar key={p.run_id} name={p.name} size="sm" />)}</span>
      )}
      <div className="icon" style={data.iconColor ? { background: data.iconColor } : undefined}>{data.icon}</div>
      <div>
        <div className="t">{data.title}</div>
        {data.sub && <div className="m">{data.sub}</div>}
        {data.techLine && <div className="tm">{data.techLine}</div>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function ZoneNode({ data }: NodeProps<Node<{ label: string }>>) {
  return <div className="group-node"><span>{data.label}</span></div>
}

const nodeTypes = { biz: BizNode, zone: ZoneNode }

type Props = { live: Live | undefined; pending: number; stats?: Record<string, NodeStat> }

export function LiveFlow({ live, pending, stats }: Props) {
  const { on: tech } = useTech()
  const navigate = useNavigate()

  const { nodes, edges } = useMemo(() => {
    const at: Record<string, { run_id: string; name: string }[]> = {}
    const entryBusy: Record<string, { run_id: string; name: string }[]> = {}
    for (const a of live?.active ?? []) {
      const biz = a.status === 'queued' ? null : BIZ_OF[a.node_id] ?? 'reads'
      if (biz) (at[biz] ??= []).push(a)
      else (entryBusy[a.channel ?? 'web_chat'] ??= []).push(a)
    }
    const techLine = (biz: string) => {
      if (!tech || !stats) return undefined
      return GROUPS[biz].map((id) => {
        const s = stats[id]
        if (!s) return `${id}: no runs`
        return s.human ? `${id} · human · ${duration(s.avg_ms)}` : `${id} · ${duration(s.avg_ms)}${s.avg_cost_usd ? ` · ${usd(s.avg_cost_usd)}` : ''}`
      }).join('\n')
    }
    const today = live?.today
    const biz = (id: string, x: number, y: number, d: Omit<BizData, 'people'>): Node<BizData> => ({
      id, type: 'biz', position: { x, y }, draggable: false, selectable: false,
      data: { ...d, people: at[id] ?? [], techLine: d.techLine ?? techLine(id) },
    })
    const entry = (id: string, y: number): Node<BizData> => ({
      id: `in-${id}`, type: 'biz', position: { x: 0, y }, draggable: false, selectable: false,
      data: { title: CHANNEL[id].label, sub: '', icon: CHANNEL[id].icon, kind: 'entry', iconColor: CHANNEL[id].color,
              people: entryBusy[id] ?? [], techLine: tech ? (id === 'email' ? 'IMAP poll · n8n 1/min' : id === 'web_form' ? 'POST /api/forms/contact' : 'POST /api/test-message') : undefined },
    })

    const nodes: Node[] = [
      { id: 'zone', type: 'zone', position: { x: 168, y: 96 }, style: { width: 640, height: tech ? 240 : 196 }, draggable: false, selectable: false, zIndex: -1, data: { label: '✦ Your assistant' } },
      entry('email', 104), entry('web_form', 196), entry('web_chat', 288),
      biz('reads', 184, 130, { title: 'Reads the message', sub: 'Any of 4 languages', icon: '💬' }),
      biz('knows', 340, 130, { title: 'Checks your services & prices', sub: 'From your website', icon: '📖' }),
      biz('writes', 496, 130, { title: 'Writes a reply', sub: 'In their language', icon: '✍️' }),
      biz('checks', 652, 130, { title: 'Double-checks every fact', sub: 'Fixes what it can’t back up', icon: '✅' }),
      biz('send', 852, 8, { title: 'Sends it', sub: today ? `${today.sent_on_its_own} on its own today` : 'On its own', icon: '📤', kind: 'send' }),
      biz('ask', 852, 292, { title: 'Asks you first', sub: "When it isn't sure", icon: '🙋', kind: 'ask', badge: pending }),
      biz('saved', 1036, 150, { title: 'Saved to leads', sub: 'Scored & sorted', icon: '⭐' }),
    ]
    const busy = (id: string) => (at[id]?.length ?? 0) > 0
    const line = (source: string, target: string, opts: Partial<Edge> & { color?: string; dashed?: boolean } = {}): Edge => ({
      id: `${source}-${target}`, source, target, type: 'smoothstep', label: opts.label,
      animated: busy(target), style: { stroke: opts.color ?? 'rgba(101, 167, 194, 0.38)', strokeWidth: 2, strokeDasharray: opts.dashed ? '6 5' : undefined },
      labelStyle: { fill: '#9CC2D3', fontSize: 11.5, fontFamily: 'Inter' }, labelBgStyle: { fill: '#042933' }, labelBgPadding: [5, 2], labelBgBorderRadius: 5,
    })
    const edges: Edge[] = [
      line('in-email', 'reads'), line('in-web_form', 'reads'), line('in-web_chat', 'reads'),
      line('reads', 'knows'), line('knows', 'writes'), line('writes', 'checks'),
      line('checks', 'send', { label: 'sure → send', color: '#65A7C2' }),
      line('checks', 'ask', { label: 'unsure → you', color: '#E39B3A', dashed: true }),
      line('ask', 'send', { label: 'you approve', dashed: true }),
      line('send', 'saved'), line('ask', 'saved', { dashed: true }),
    ]
    return { nodes, edges }
  }, [live, pending, stats, tech])

  return (
    <div className="flow">
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.05 }} minZoom={0.15}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={false}
        zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false} preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.id === 'ask') navigate('/needs-you')
          else if (tech) navigate('/automations/lead_handler')
        }}
      >
        <Background color="rgba(199, 229, 242, 0.09)" gap={20} size={1.4} />
      </ReactFlow>
    </div>
  )
}
