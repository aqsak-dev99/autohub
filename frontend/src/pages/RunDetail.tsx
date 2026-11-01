import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Step } from '../api'
import { FlowGraph } from '../components/FlowGraph'
import { ErrorBox, Stat, StatusChip } from '../components/ui'
import { ago, duration, json, usd } from '../format'

const STEP_COLOR: Record<string, string> = {
  succeeded: '#65A7C2', running: '#C7E5F2', waiting: '#E9A84C', failed: '#F08B7A', skipped: 'rgba(101, 167, 194, 0.25)',
}

function StepPanel({ step, label }: { step: Step | undefined; label: string }) {
  if (!step) return <div className="card empty">This step didn't run. Click a coloured node to inspect it.</div>
  const tokens = step.prompt_tokens + step.completion_tokens
  return (
    <div className="card pad stack">
      <div className="stack" style={{ gap: 4 }}>
        <span className="faint mono">step · {step.node_id}</span>
        <h2>{label}</h2>
        <StatusChip status={step.status} />
      </div>
      <div className="stats-grid">
        <Stat label="Duration" value={step.status === 'waiting' ? 'waiting' : duration(step.duration_ms)} />
        <Stat label="Cost" value={usd(step.cost_usd)} />
        <Stat label="Tokens in / out" value={tokens ? `${step.prompt_tokens} / ${step.completion_tokens}` : '—'} />
        <Stat label="Attempts" value={step.attempts} />
      </div>
      <span className="faint">Model <span className="mono" style={{ color: 'var(--text)' }}>{step.model ?? '—'}</span></span>
      {step.error && <div className="error mono" style={{ fontSize: 12 }}>{step.error}</div>}
      <div className="stack" style={{ gap: 6 }}><h3>Input</h3><pre className="code" dir="auto">{json(step.input)}</pre></div>
      <div className="stack" style={{ gap: 6 }}><h3>Output</h3><pre className="code" dir="auto">{json(step.output)}</pre></div>
    </div>
  )
}

export default function RunDetailPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const run = useQuery({
    queryKey: ['run', id],
    queryFn: () => api.run(id),
    // live replay: poll while the run is still moving
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1200 : false),
  })
  const automations = useQuery({ queryKey: ['automations'], queryFn: api.automations })
  const slug = automations.data?.find((a) => a.id === run.data?.automation_id)?.slug
  const automation = useQuery({ queryKey: ['automation', slug], queryFn: () => api.automation(slug!), enabled: !!slug })
  const retry = useMutation({ mutationFn: () => api.retryRun(id), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', id] }) })

  const r = run.data
  const steps = r?.steps ?? []
  const active = !!r && ['queued', 'running'].includes(r.status)
  // follow the newest step while the run is live, unless the user picked one
  useEffect(() => {
    if (!selected && steps.length) setSelected(steps[steps.length - 1].node_id)
  }, [steps.length, selected]) // eslint-disable-line react-hooks/exhaustive-deps

  const labels = new Map((automation.data?.graph.nodes ?? []).map((n) => [n.id, n.data.label]))
  const step = steps.find((s) => s.node_id === selected)
  const totalMs = steps.reduce((sum, s) => sum + (s.status === 'waiting' ? 0 : s.duration_ms), 0)
  const waitingStep = steps.find((s) => s.status === 'waiting')

  return (
    <>
      <div className="page-head">
        <div>
          <div className="crumbs"><Link to="/runs">Runs</Link> › {automation.data?.name ?? '…'} › <span className="mono">{id.slice(0, 8)}…</span></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <h1>{r?.label ?? automation.data?.name ?? 'Run'}</h1>
            {r && <StatusChip status={r.status} />}
          </div>
        </div>
        {r && (
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="stack" style={{ gap: 0 }}><span className="faint">Started</span><span>{ago(r.created_at)}</span></div>
            <div className="stack" style={{ gap: 0 }}><span className="faint">System time</span><span className="mono">{duration(totalMs)}</span></div>
            <div className="stack" style={{ gap: 0 }}><span className="faint">Tokens</span><span className="mono">{r.total_tokens.toLocaleString()}</span></div>
            <div className="stack" style={{ gap: 0 }}><span className="faint">Cost</span><span className="mono">{usd(r.total_cost_usd)}</span></div>
            {r.status === 'failed' && <button className="btn primary" onClick={() => retry.mutate()} disabled={retry.isPending}>Retry run</button>}
            {r.status === 'waiting_approval' && <Link className="btn primary" to="/needs-you">Review it →</Link>}
            {r.automation_id && r.input?.message !== undefined && <Link className="btn" to={`/conversations/${r.id}`}>Business view</Link>}
          </div>
        )}
      </div>
      <ErrorBox error={run.error || retry.error} />
      {r?.error && <div className="error mono" style={{ fontSize: 12 }}>{r.error}</div>}
      <div className="home-grid">
        <section className="card" style={{ minWidth: 0 }} aria-label="Run replay">
          <div className="card-head">
            <span className="legend">
              <span><i style={{ background: '#65A7C2' }} />Done</span>
              <span><i style={{ background: '#C7E5F2' }} />Running</span>
              <span><i style={{ background: '#E9A84C' }} />Waiting</span>
              <span><i style={{ background: '#F08B7A' }} />Failed</span>
              <span><i style={{ border: '1px dashed #7598AA' }} />Skipped / not reached</span>
            </span>
            <span className="faint">{active ? 'Live: updating as it runs' : 'Click a node to inspect it'}</span>
          </div>
          {automation.data && <FlowGraph automation={automation.data} steps={steps} runActive={active} selected={selected} onSelect={setSelected} />}
          <div className="card-head" style={{ borderTop: '1px solid var(--line)', borderBottom: 0 }}>
            <div className="timeline" aria-label="Time per step">
              {steps.map((s) => (
                <div key={s.node_id} title={`${labels.get(s.node_id) ?? s.node_id}: ${duration(s.duration_ms)}`}
                  style={{ flex: s.status === 'waiting' ? 4 : Math.max(1, s.duration_ms), background: STEP_COLOR[s.status] }} />
              ))}
            </div>
            <span className="faint mono">{duration(totalMs)}{waitingStep ? ' + waiting for a person' : ''}</span>
          </div>
        </section>
        <aside style={{ minWidth: 0 }}>
          <StepPanel step={step} label={labels.get(selected ?? '') ?? selected ?? ''} />
        </aside>
      </div>
    </>
  )
}
