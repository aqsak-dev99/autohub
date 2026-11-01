import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ErrorBox } from '../components/ui'

const TRIGGERS: Record<string, string> = {
  webhook: 'Email or website form',
  upload: 'File upload',
  schedule: 'n8n schedule',
  manual: 'Run by hand',
}

export default function Automations() {
  const automations = useQuery({ queryKey: ['automations'], queryFn: api.automations })
  return (
    <>
      <div className="page-head">
        <div><div className="crumbs mono">technical view</div><h1>Automations</h1><div className="sub">Every automation the hub runs, with its workflow map and heatmap.</div></div>
      </div>
      <ErrorBox error={automations.error} />
      <div className="kpis" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
        {automations.data?.map((a) => (
          <Link key={a.slug} to={`/automations/${a.slug}`} className="card" style={{ color: 'inherit' }}>
            <div className="card-body stack" style={{ gap: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <h2>{a.name}</h2>
                <span className="chip">{TRIGGERS[a.trigger] ?? a.trigger}</span>
              </div>
              <p className="muted" style={{ margin: 0 }}>{a.description}</p>
              <span className="faint">Open the map and heatmap →</span>
            </div>
          </Link>
        ))}
      </div>
    </>
  )
}
