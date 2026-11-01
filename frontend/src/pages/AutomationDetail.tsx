import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type NodeStat } from '../api'
import { FlowGraph, RAMP_COLORS, type HeatMetric } from '../components/FlowGraph'
import { ErrorBox, Kpi, StatusChip } from '../components/ui'
import { ago, duration, pct, usd } from '../format'

const METRICS: { id: HeatMetric; label: string; low: string; high: string }[] = [
  { id: 'latency', label: 'Latency', low: 'Fast', high: 'Slow' },
  { id: 'cost', label: 'Cost', low: 'Cheap', high: 'Costly' },
  { id: 'failure', label: 'Failure rate', low: 'Reliable', high: 'Fails most' },
]

function value(stat: NodeStat, metric: HeatMetric) {
  return metric === 'latency' ? stat.avg_ms ?? 0 : metric === 'cost' ? stat.avg_cost_usd ?? 0 : stat.failure_rate ?? 0
}
function show(stat: NodeStat, metric: HeatMetric) {
  return metric === 'latency' ? duration(stat.avg_ms) : metric === 'cost' ? usd(stat.avg_cost_usd) : pct(stat.failure_rate)
}

export default function AutomationDetailPage() {
  const { slug = '' } = useParams()
  const navigate = useNavigate()
  const [metric, setMetric] = useState<HeatMetric>('latency')
  const automation = useQuery({ queryKey: ['automation', slug], queryFn: () => api.automation(slug) })
  const stats = useQuery({ queryKey: ['nodeStats', slug], queryFn: () => api.nodeStats(slug, 7), refetchInterval: 10000 })
  const runs = useQuery({ queryKey: ['runs', slug, 'recent'], queryFn: () => api.runs({ automation: slug, limit: 6 }), refetchInterval: 5000 })
  const trigger = useMutation({ mutationFn: () => api.triggerRun(slug, slug === 'daily_digest' ? { hours: 24, source: 'dashboard' } : {}),
    onSuccess: (run) => navigate(`/runs/${run.id}`) })

  const m = METRICS.find((x) => x.id === metric)!
  const nodes = stats.data?.nodes ?? {}
  const labels = new Map((automation.data?.graph.nodes ?? []).map((n) => [n.id, n.data.label]))
  const ranked = Object.entries(nodes)
    .filter(([, s]) => !s.human && value(s, metric) > 0)
    .sort((a, b) => value(b[1], metric) - value(a[1], metric))
  const top = ranked[0]
  const total = ranked.reduce((sum, [, s]) => sum + value(s, metric), 0)
  const approvalShare = nodes.approval && nodes.score ? nodes.approval.count / nodes.score.count : null

  return (
    <>
      <div className="page-head">
        <div>
          <div className="crumbs"><Link to="/automations">Automations</Link> › {automation.data?.name}</div>
          <h1>{automation.data?.name ?? slug}</h1>
          <p className="muted" style={{ margin: '6px 0 0', maxWidth: 720 }}>{automation.data?.description}</p>
        </div>
        {slug !== 'lead_handler' && (
          <button className="btn primary" onClick={() => trigger.mutate()} disabled={trigger.isPending}>Run now</button>
        )}
      </div>
      <ErrorBox error={automation.error || stats.error || trigger.error} />
      {stats.data && (
        <div className="kpis">
          <Kpi label="Runs · 7 days" value={stats.data.runs} />
          {slug === 'lead_handler' && <Kpi label="Sent to review" value={pct(approvalShare)} hint="of drafted replies" />}
          {top && <Kpi label={`Slowest step`} value={labels.get(Object.entries(nodes).filter(([, s]) => !s.human)
            .sort((a, b) => (b[1].avg_ms ?? 0) - (a[1].avg_ms ?? 0))[0]?.[0] ?? '') ?? '—'} />}
        </div>
      )}
      <div className="home-grid">
        <section className="card" style={{ minWidth: 0 }} aria-label="Workflow heatmap">
          <div className="card-head">
            <div className="seg" role="group" aria-label="Heatmap metric">
              {METRICS.map((x) => (
                <button key={x.id} className={x.id === metric ? 'on' : ''} aria-pressed={x.id === metric} onClick={() => setMetric(x.id)}>
                  {x.label}
                </button>
              ))}
            </div>
            <span className="legend">
              {m.low}
              {RAMP_COLORS.map((c) => <i key={c} style={{ borderRadius: 3, width: 20, background: c }} />)}
              {m.high}
            </span>
          </div>
          {automation.data && <FlowGraph automation={automation.data} heat={{ metric, nodes }} />}
        </section>
        <aside className="stack" style={{ minWidth: 0 }}>
          {top ? (
            <div className="card pad stack" style={{ gap: 8 }}>
              <span style={{ color: 'var(--warm)', fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Hotspot</span>
              <h2>{labels.get(top[0]) ?? top[0]} {metric === 'failure' ? `fails ${show(top[1], metric)}` : `takes ${total ? Math.round((value(top[1], metric) / total) * 100) : 0}% of ${metric === 'cost' ? 'spend' : 'run time'}`}</h2>
              <p className="muted" style={{ margin: 0 }}>
                Averaged over {top[1].count} runs of this step in the last 7 days
                {top[1].avg_tokens ? `, about ${top[1].avg_tokens.toLocaleString()} tokens each` : ''}.
              </p>
            </div>
          ) : (
            <div className="card empty">No runs in the last 7 days yet</div>
          )}
          <div className="card pad stack">
            <h3>Steps by {m.label.toLowerCase()}</h3>
            {ranked.slice(0, 5).map(([id, s]) => (
              <div key={id} className="stack" style={{ gap: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>{labels.get(id) ?? id}</span><span className="mono muted">{show(s, metric)}</span></div>
                <div className="bar"><div style={{ width: `${(value(s, metric) / value(ranked[0][1], metric)) * 100}%` }} /></div>
              </div>
            ))}
            {nodes.approval && <span className="faint">Human approval isn't on this scale: its time is a person's response time ({duration(nodes.approval.avg_ms)} on average).</span>}
          </div>
          <div className="card">
            <div className="card-head"><h2>Recent runs</h2><Link to="/runs">All</Link></div>
            <div className="stack" style={{ gap: 0 }}>
              {runs.data?.map((r) => (
                <Link key={r.id} to={`/runs/${r.id}`} className="list-item" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
                  <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <span className="clip">{r.label ?? r.id.slice(0, 8)}</span><StatusChip status={r.status} />
                  </span>
                  <span className="faint">{ago(r.created_at)} · {usd(r.total_cost_usd)}</span>
                </Link>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </>
  )
}
