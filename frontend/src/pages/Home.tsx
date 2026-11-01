import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { LiveFlow } from '../components/LiveFlow'
import { ReviewCard } from '../components/ReviewCard'
import { TryIt } from '../components/TryIt'
import { Avatar, ErrorBox, Kpi } from '../components/ui'
import { OWNER_NAME } from '../config'
import { ago, BANDS, usd } from '../format'
import { channelLabel, friendlyReason, greeting, language, rupeesFromUsd, statusText, wants } from '../plain'
import { useTech } from '../tech'
import { useAuth } from '../auth'

export default function Home() {
  const { on: tech } = useTech()
  const { isViewer } = useAuth()
  const [trying, setTrying] = useState(false)
  const live = useQuery({ queryKey: ['live'], queryFn: api.live, refetchInterval: 2000 })
  const week = useQuery({ queryKey: ['overview', 7], queryFn: () => api.overview(7), refetchInterval: 10000 })
  const month = useQuery({ queryKey: ['overview', 30], queryFn: () => api.overview(30), refetchInterval: 30000 })
  const approvals = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => api.approvals('pending'), refetchInterval: 5000 })
  const leads = useQuery({ queryKey: ['leads', 'recent'], queryFn: () => api.leads(), refetchInterval: 5000 })
  const stats = useQuery({ queryKey: ['nodeStats', 'lead_handler'], queryFn: () => api.nodeStats('lead_handler', 7), enabled: tech })

  const today = live.data?.today
  const pending = approvals.data ?? []
  const w = week.data
  const m = month.data
  const active = live.data?.active.length ?? 0
  // the hot lead with the biggest budget band (bands are ordered smallest to largest)
  const order = ['under_150k', '150k_400k', '400k_1m', 'over_1m']
  const bestBand = (w?.hot ?? []).map((h) => h.budget_band ?? '').filter((b) => order.includes(b)).sort((a, b) => order.indexOf(b) - order.indexOf(a))[0]

  return (
    <>
      <div className="hero">
        <div className="page-head">
        <div>
          <h1>{isViewer ? `${greeting()}! This is flowpath’s assistant` : `${greeting()}, ${OWNER_NAME}`}</h1>
          <div className="sub">
            {today && today.received > 0
              ? <>Your assistant answered <b style={{ color: 'var(--text)' }}>{today.received - today.spam} customer{today.received - today.spam === 1 ? '' : 's'}</b> today.{' '}</>
              : <>No messages yet today. </>}
            {pending.length > 0 ? <>{pending.length} {pending.length === 1 ? 'reply is' : 'replies are'} waiting for your OK.</> : <>Nothing is waiting for you.</>}
            {tech && w && m && (
              <span className="mono faint" style={{ display: 'block', marginTop: 4 }}>
                7d: {w.runs} runs · median {w.median_run_seconds ?? '—'} s · success {w.success_rate !== null ? Math.round(w.success_rate * 100) : '—'}% · 30d cost {usd(m.cost_usd, 4)} ({rupeesFromUsd(m.cost_usd)}) · {m.tokens.toLocaleString()} tokens
              </span>
            )}
          </div>
        </div>
        <button className="btn primary" onClick={() => setTrying(true)}>＋ Try it: send a test message</button>
      </div>
      </div>
      {trying && <TryIt onClose={() => setTrying(false)} />}
      <ErrorBox error={live.error || week.error} />

      <div className="home-grid hero-cards">
        <div className="stack" style={{ gap: 18, minWidth: 0 }}>
          <div className="kpis">
            <Kpi label="Customers today" value={today ? today.received - today.spam : '—'} spark={w?.series.map((d) => d.runs)}
              hint={today ? `${today.sent_on_its_own} answered on their own` : undefined}
              tech={today ? `${today.received} leads · ${today.spam} spam · ${today.asked_you} held` : undefined} />
            <Kpi label="Average reply time" value={w?.median_run_seconds ? `${Math.round(w.median_run_seconds)} sec` : '—'}
              hint="Day and night, in 4 languages" tech={w ? `median of ${w.succeeded} runs · 7d` : undefined} />
            <Kpi label="Hot leads this week" value={w?.hot_leads ?? '—'}
              hint={bestBand && BANDS[bestBand] ? `Top budget: ${BANDS[bestBand]} a month` : 'Worth calling first'}
              tech={w ? `score ≥ 70 · ${w.leads} leads total` : undefined} />
            <Kpi label="Assistant cost this month" value={m ? rupeesFromUsd(m.cost_usd) : '—'} spark={w?.series.map((d) => d.cost_usd)}
              hint={m && m.leads ? `About ${rupeesFromUsd(m.cost_usd / m.leads)} per customer` : undefined}
              tech={m ? `${usd(m.cost_usd, 4)} · ${m.tokens.toLocaleString()} tokens` : undefined} />
          </div>
          <section className="card flow-card" aria-label="Live view">
            <div className="card-head">
              <span className="pulse-dot" aria-hidden style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--sky)', boxShadow: '0 0 12px var(--sky)' }} />
              <h2>Live: what your assistant is doing</h2>
              <span className="spacer" />
              <span className="faint">{active ? `${active} customer${active === 1 ? '' : 's'} being answered now` : 'Waiting for the next message'}</span>
              {tech && <Link to="/automations/lead_handler" className="faint mono">heatmap →</Link>}
            </div>
            <LiveFlow live={live.data} pending={pending.length} stats={stats.data?.nodes} />
          </section>

          <div className="feed">
            {(leads.data ?? []).slice(0, 4).map((l) => {
              const st = statusText(l)
              return (
                <Link key={l.id} to={l.run_id ? `/conversations/${l.run_id}` : '/leads'} className="ev">
                  <b>{l.name || l.contact}</b> · {language(l.language)} · {channelLabel(l.channel)}<br />
                  <span className={`tone-${st.tone}`}>{st.text}</span> · {wants(l)} · {ago(l.created_at)}
                </Link>
              )
            })}
          </div>
        </div>

        <aside className="stack" style={{ gap: 12 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2>Needs your OK {pending.length > 0 && <span className="count" style={{ marginLeft: 6 }}>{pending.length}</span>}</h2>
            {pending.length > 1 && <Link to="/needs-you" className="faint">See all</Link>}
          </div>
          <p className="muted" style={{ fontSize: 13 }}>Replies your assistant wrote but wasn't allowed to send alone.</p>
          {pending.length === 0 && <div className="card empty">All caught up. Nothing needs you. 🎉</div>}
          {pending[0] && <ReviewCard approval={pending[0]} compact />}
          {pending.slice(1, 5).map((a) => (
            <Link key={a.id} to={`/needs-you/${a.id}`} className="card list-item" style={{ borderRadius: 12, border: '1px solid var(--line)' }}>
              <Avatar name={a.payload.name || a.payload.contact} />
              <span className="body">
                <span className="title clip">{a.payload.name || a.payload.contact}{a.payload.qualification.business_type ? ` · ${a.payload.qualification.business_type}` : ''}</span>
                <span className="snippet">{friendlyReason(a.payload.reasons[0] ?? '')}</span>
              </span>
              <span className="tone-run" style={{ fontSize: 13 }}>Review</span>
            </Link>
          ))}
        </aside>
      </div>
    </>
  )
}
