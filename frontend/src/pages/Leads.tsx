import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Avatar, ErrorBox, TempChip } from '../components/ui'
import { BANDS, ago, rupees } from '../format'
import { channelLabel, statusText, wants } from '../plain'
import { useTech } from '../tech'

const TEMPS = [
  { id: '', label: 'All leads' }, { id: 'hot', label: 'Hot' }, { id: 'warm', label: 'Warm' }, { id: 'cold', label: 'Cold' },
]

export default function Leads() {
  const { on: tech } = useTech()
  const navigate = useNavigate()
  const [temperature, setTemperature] = useState('')
  const leads = useQuery({ queryKey: ['leads', temperature], queryFn: () => api.leads({ temperature }), refetchInterval: 5000 })
  const list = (leads.data ?? []).filter((l) => l.temperature && l.temperature !== 'not_a_lead')
  const others = (leads.data ?? []).length - list.length

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Leads</h1>
          <div className="sub">Possible clients, scored by how ready they are to work with you. Hottest first is a good place to start.</div>
        </div>
        <div className="seg" role="group" aria-label="Filter">
          {TEMPS.map((t) => <button key={t.id} className={temperature === t.id ? 'on' : ''} onClick={() => setTemperature(t.id)}>{t.label}</button>)}
        </div>
      </div>
      <ErrorBox error={leads.error} />
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Who</th><th>Wants</th><th>Budget a month</th><th>Start</th><th>Lead</th><th>Status</th><th>When</th>{tech && <th>Confidence</th>}</tr>
            </thead>
            <tbody>
              {[...list].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).map((l) => {
                const st = statusText(l)
                return (
                  <tr key={l.id} className="clickable" onClick={() => l.run_id && navigate(`/conversations/${l.run_id}`)}>
                    <td>
                      <div className="row" style={{ flexWrap: 'nowrap', gap: 10 }}>
                        <Avatar name={l.name || l.contact} size="sm" />
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600 }}>{l.name || l.contact}</div>
                          <div className="faint clip" style={{ maxWidth: 220 }}>{l.business_type ?? channelLabel(l.channel)}</div>
                        </div>
                      </div>
                    </td>
                    <td className="muted">{wants(l)}</td>
                    <td className="muted nowrap">{l.monthly_budget_pkr ? rupees(l.monthly_budget_pkr) : BANDS[l.budget_band ?? 'unknown']}</td>
                    <td className="muted">{l.timeline ?? '—'}</td>
                    <td className="nowrap"><TempChip temperature={l.temperature} score={l.score} /></td>
                    <td className="nowrap"><span className={`tone-${st.tone}`} style={{ fontSize: 13 }}>{st.text}</span></td>
                    <td className="faint nowrap">{ago(l.created_at)}</td>
                    {tech && <td className="mono faint">{l.confidence?.toFixed(2) ?? '—'}</td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
          {list.length === 0 && !leads.isLoading && <div className="empty">No leads here yet.</div>}
        </div>
      </section>
      {others > 0 && <p className="faint">{others} other message{others === 1 ? '' : 's'} (spam, job applications, existing clients) are in Conversations.</p>}
    </>
  )
}
