import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ErrorBox, StatusChip } from '../components/ui'
import { ago, usd } from '../format'

export default function Runs() {
  const [automation, setAutomation] = useState('')
  const [status, setStatus] = useState('')
  const automations = useQuery({ queryKey: ['automations'], queryFn: api.automations })
  const runs = useQuery({
    queryKey: ['runs', automation, status],
    queryFn: () => api.runs({ automation, status, limit: 100 }),
    refetchInterval: 4000,
  })
  const names = new Map((automations.data ?? []).map((a) => [a.id, a.name]))

  return (
    <>
      <div className="page-head">
        <div><div className="crumbs mono">technical view</div><h1>Runs</h1><div className="sub">Every execution of every automation, step by step.</div></div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <select className="field" value={automation} onChange={(e) => setAutomation(e.target.value)} aria-label="Automation">
            <option value="">All automations</option>
            {automations.data?.map((a) => <option key={a.slug} value={a.slug}>{a.name}</option>)}
          </select>
          <select className="field" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">Any status</option>
            {['queued', 'running', 'waiting_approval', 'succeeded', 'failed'].map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
      </div>
      <ErrorBox error={runs.error} />
      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Automation</th><th>About</th><th>Status</th><th>Tokens</th><th>Cost</th><th>Started</th><th>Error</th></tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((run) => (
                <tr key={run.id}>
                  <td><Link to={`/runs/${run.id}`}>{names.get(run.automation_id) ?? run.automation_id}</Link></td>
                  <td className="muted">{run.label ?? '—'}</td>
                  <td><StatusChip status={run.status} /></td>
                  <td className="mono">{run.total_tokens.toLocaleString()}</td>
                  <td className="mono">{usd(run.total_cost_usd)}</td>
                  <td className="faint">{ago(run.created_at)}</td>
                  <td className="faint clip" style={{ maxWidth: 280 }} title={run.error ?? ''}>{run.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.data?.length === 0 && <div className="empty">No runs match</div>}
        </div>
      </section>
    </>
  )
}
