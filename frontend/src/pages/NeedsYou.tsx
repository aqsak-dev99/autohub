import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { ReviewCard } from '../components/ReviewCard'
import { Avatar, ErrorBox, StatusChip } from '../components/ui'
import { ago } from '../format'
import { friendlyReason } from '../plain'

export default function NeedsYou() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'pending' | 'all'>('pending')
  const approvals = useQuery({ queryKey: ['approvals', tab], queryFn: () => api.approvals(tab), refetchInterval: 5000 })
  const list = approvals.data ?? []
  const current = list.find((a) => String(a.id) === id) ?? list[0]

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Needs you</h1>
          <div className="sub">Replies your assistant wrote but wasn't allowed to send on its own. Check them, change them if you like, and send.</div>
        </div>
        <div className="seg" role="group" aria-label="Show">
          <button className={tab === 'pending' ? 'on' : ''} onClick={() => setTab('pending')}>Waiting</button>
          <button className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>History</button>
        </div>
      </div>
      <ErrorBox error={approvals.error} />
      {list.length === 0 && !approvals.isLoading ? (
        <div className="card empty">{tab === 'pending' ? 'All caught up. Nothing needs you. 🎉' : 'Nothing has needed you yet.'}</div>
      ) : (
        <div className="two-col">
          <section className="card" aria-label="Replies to review" style={{ overflow: 'hidden' }}>
            {list.map((a) => (
              <button key={a.id} className={`list-item ${current?.id === a.id ? 'active' : ''}`} onClick={() => navigate(`/needs-you/${a.id}`)}>
                <Avatar name={a.payload.name || a.payload.contact} />
                <span className="body">
                  <span className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <span className="title clip">{a.payload.name || a.payload.contact}</span>
                    <span className="faint" style={{ whiteSpace: 'nowrap' }}>{ago(a.created_at)}</span>
                  </span>
                  <span className="snippet clip" dir="auto">{a.payload.message}</span>
                  <span className="faint clip">{a.status === 'pending' ? friendlyReason(a.payload.reasons[0] ?? '') : <StatusChip status={a.status} />}</span>
                </span>
              </button>
            ))}
          </section>
          <section style={{ minWidth: 0 }}>
            {current && <ReviewCard approval={current} onDone={() => navigate('/needs-you')} />}
          </section>
        </div>
      )}
    </>
  )
}
