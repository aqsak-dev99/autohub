import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Approval } from '../api'
import { ago, rupees } from '../format'
import { BANDS } from '../format'
import { channelLabel, friendlyReason, language, wants } from '../plain'
import { useTech } from '../tech'
import { Avatar, ErrorBox, StatusChip, TempChip } from './ui'

export type Claim = { text: string; kind: string; supported: boolean }
export const CHECKED_KINDS = new Set(['fact_about_flowpath', 'commitment'])

/** One reply waiting for the owner: why it was held, what the customer said, the draft, and the evidence. */
export function ReviewCard({ approval, compact = false, onDone }: { approval: Approval; compact?: boolean; onDone?: () => void }) {
  const { on: tech } = useTech()
  const p = approval.payload
  const queryClient = useQueryClient()
  const [reply, setReply] = useState(p.reply)
  const [editing, setEditing] = useState(!compact)
  const [note, setNote] = useState('')
  useEffect(() => { setReply(p.reply); setNote(''); setEditing(!compact) }, [approval.id, p.reply, compact])

  const run = useQuery({ queryKey: ['run', approval.run_id], queryFn: () => api.run(approval.run_id) })
  const claims = ((run.data?.steps.find((s) => s.node_id === 'score')?.output as { claims?: Claim[] } | null)?.claims ?? [])
    .filter((c) => CHECKED_KINDS.has(c.kind))
  const bad = claims.filter((c) => !c.supported)

  const decide = useMutation({
    mutationFn: (action: 'approve' | 'edit' | 'reject') =>
      api.decide(approval.id, action === 'edit' ? { action, reply, note: note || undefined } : { action, note: note || undefined }),
    onSuccess: () => {
      for (const key of ['approvals', 'overview', 'live', 'leads', 'conversation', 'run']) queryClient.invalidateQueries({ queryKey: [key] })
      onDone?.()
    },
  })
  const edited = reply.trim() !== p.reply.trim()
  const pending = approval.status === 'pending'
  const q = p.qualification
  const goesTo = p.channel === 'web_chat' ? 'shown in the website chat' : `emailed to ${p.contact}`

  return (
    <div className="card pad stack" style={{ gap: 12, boxShadow: compact ? 'var(--shadow)' : undefined, borderColor: compact ? 'var(--sky-400)' : undefined }}>
      <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
        <Avatar name={p.name || p.contact} size="lg" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>{p.name || p.contact}{q.business_type ? ` · ${q.business_type}` : ''}</div>
          <div className="faint">{channelLabel(p.channel)} · {language(p.language)} · {ago(approval.created_at)}</div>
        </div>
        {!compact && <TempChip temperature={p.temperature} score={p.score} />}
      </div>

      <div className="notice stack" style={{ gap: 4 }}>
        {p.reasons.map((r) => <span key={r}>{friendlyReason(r)}</span>)}
      </div>

      <div>
        <h3 style={{ marginBottom: 6 }}>They wrote</h3>
        <div dir="auto" style={{ whiteSpace: 'pre-wrap', fontSize: 14.5 }}>{p.message}</div>
        {p.translation?.message_en && <div className="translation"><b>In English:</b> {p.translation.message_en}</div>}
        {!compact && (
          <div className="chips" style={{ marginTop: 10 }}>
            {wants({ services: q.services, intent: p.intent }) !== '—' && <span className="tag">Wants: {wants({ services: q.services, intent: p.intent })}</span>}
            <span className="tag">Budget: {q.monthly_budget_pkr ? rupees(q.monthly_budget_pkr) : BANDS[q.budget_band] ?? 'Not stated'}</span>
            {q.timeline && <span className="tag">Start: {q.timeline}</span>}
          </div>
        )}
      </div>

      <div style={{ background: '#F2F9FA', borderRadius: 12, padding: '12px 13px' }}>
        <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--teal-500)', letterSpacing: '0.04em', marginBottom: 6 }}>
          {pending ? "YOUR ASSISTANT'S REPLY" : 'THE REPLY'}
        </div>
        {pending && editing ? (
          <textarea className="field" rows={compact ? 5 : 7} dir="auto" value={reply} onChange={(e) => setReply(e.target.value)} aria-label="Reply" />
        ) : (
          <div dir="auto" style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{pending ? reply : approval.final_payload?.reply ?? p.reply}</div>
        )}
        {p.translation?.reply_en && (
          <div className="translation">
            <b>In English:</b> {p.translation.reply_en}
            {edited && <div className="faint" style={{ marginTop: 4 }}>This translation is of the original draft, before your changes.</div>}
          </div>
        )}
      </div>

      {run.isLoading ? <span className="faint">Checking facts…</span> : claims.length > 0 && (
        compact ? (
          <span className={bad.length ? 'tone-fail' : 'tone-ok'} style={{ fontSize: 13 }}>
            {bad.length ? `✗ ${bad.length} of ${claims.length} facts aren't on your website` : `✓ ${claims.length === 1 ? 'The fact matches' : `All ${claims.length} facts match`} your website`}
          </span>
        ) : (
          <div className="stack" style={{ gap: 6 }}>
            <h3>Fact check</h3>
            {claims.map((c, i) => (
              <div key={i} className="row" style={{ flexWrap: 'nowrap', alignItems: 'baseline', gap: 8 }}>
                <span className={c.supported ? 'tone-ok' : 'tone-fail'}>{c.supported ? '✓' : '✗'}</span>
                <span dir="auto">“{c.text}” <span className="faint">{c.supported ? 'matches your website' : "isn't on your website"}</span></span>
              </div>
            ))}
          </div>
        )
      )}

      {tech && (
        <div className="tech-line">
          confidence {p.confidence.toFixed(2)} · intent {p.intent} · reasons: {p.reasons.join(' | ')}<br />
          passages: {p.passages.map((x) => `${x.id}${x.score !== null ? `(${x.score.toFixed(1)})` : '(pinned)'}`).join(', ')}<br />
          <Link to={`/runs/${approval.run_id}`}>open run graph →</Link>
        </div>
      )}

      {pending ? (
        <>
          {!compact && <input className="field" placeholder="Note to yourself (optional): why you changed or skipped it" value={note} onChange={(e) => setNote(e.target.value)} />}
          <ErrorBox error={decide.error} />
          <div className="row">
            {edited ? (
              <button className="btn primary" style={{ flex: 1 }} disabled={decide.isPending || !reply.trim()} onClick={() => decide.mutate('edit')}>Send my version</button>
            ) : (
              <button className="btn primary" style={{ flex: 1 }} disabled={decide.isPending} onClick={() => decide.mutate('approve')}>Approve &amp; send</button>
            )}
            {!editing && <button className="btn" onClick={() => setEditing(true)}>Edit</button>}
            <button className="btn danger" disabled={decide.isPending} onClick={() => decide.mutate('reject')}>Don't reply</button>
          </div>
          <span className="faint">It will be {goesTo}.</span>
        </>
      ) : (
        <span className="faint"><StatusChip status={approval.status} /> {ago(approval.decided_at)}</span>
      )}
      {compact && <Link to={`/conversations/${approval.run_id}`} className="faint">See how it was handled →</Link>}
    </div>
  )
}
