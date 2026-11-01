import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Lead } from '../api'
import { TryIt } from '../components/TryIt'
import { Avatar, ErrorBox, TempChip } from '../components/ui'
import { ago } from '../format'
import { channelLabel, language, statusText } from '../plain'

const FILTERS: { id: string; label: string; match: (l: Lead) => boolean }[] = [
  { id: 'all', label: 'All', match: (l) => l.status !== 'spam' },
  { id: 'wait', label: 'Waiting for you', match: (l) => l.status === 'awaiting_approval' },
  { id: 'replied', label: 'Replied', match: (l) => l.status === 'replied' },
  { id: 'spam', label: 'Spam', match: (l) => l.status === 'spam' },
]

export default function Conversations() {
  const [filter, setFilter] = useState('all')
  const [trying, setTrying] = useState(false)
  const leads = useQuery({ queryKey: ['leads', 'all'], queryFn: () => api.leads(), refetchInterval: 5000 })
  const f = FILTERS.find((x) => x.id === filter)!
  const list = (leads.data ?? []).filter(f.match)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Conversations</h1>
          <div className="sub">Every message customers sent, and how your assistant handled it. Open one to see it step by step.</div>
        </div>
        <div className="row">
          <div className="seg" role="group" aria-label="Filter">
            {FILTERS.map((x) => <button key={x.id} className={filter === x.id ? 'on' : ''} onClick={() => setFilter(x.id)}>{x.label}</button>)}
          </div>
          <button className="btn primary" onClick={() => setTrying(true)}>＋ Try it</button>
        </div>
      </div>
      {trying && <TryIt onClose={() => setTrying(false)} />}
      <ErrorBox error={leads.error} />
      <section className="card" style={{ overflow: 'hidden' }}>
        {list.length === 0 && !leads.isLoading && <div className="empty">No conversations here yet.</div>}
        {list.map((l) => {
          const st = statusText(l)
          return (
            <Link key={l.id} to={l.run_id ? `/conversations/${l.run_id}` : '#'} className="list-item">
              <Avatar name={l.name || l.contact} />
              <span className="body">
                <span className="row" style={{ gap: 8 }}>
                  <span className="title">{l.name || l.contact}</span>
                  {l.business_type && <span className="faint">· {l.business_type}</span>}
                  <span className="faint">· {channelLabel(l.channel)} · {language(l.language)}</span>
                </span>
                <span className="snippet clip" dir="auto">{l.message}</span>
              </span>
              <span className="row" style={{ flexWrap: 'nowrap', gap: 10 }}>
                <TempChip temperature={l.temperature} />
                {l.followed_up_at && <span className="tag" title="Your assistant sent one follow-up after they went quiet">Followed up</span>}
                <span className={`tone-${st.tone}`} style={{ fontSize: 13, whiteSpace: 'nowrap' }}>{st.text}</span>
                <span className="faint" style={{ whiteSpace: 'nowrap', minWidth: 74, textAlign: 'right' }}>{ago(l.created_at)}</span>
              </span>
            </Link>
          )
        })}
      </section>
    </>
  )
}
