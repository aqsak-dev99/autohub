import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Approval, type Lead, type RunDetail, type Step } from '../api'
import { CHECKED_KINDS, type Claim } from '../components/ReviewCard'
import { FlowGraph } from '../components/FlowGraph'
import { Avatar, ErrorBox } from '../components/ui'
import { BANDS, duration, json, parseDate, rupees, usd } from '../format'
import { channelLabel, friendlyReason, language, nextStep, rupeesFromUsd, scoreReasons, statusText } from '../plain'
import { useTech } from '../tech'

type StoryItem = { key: string; icon: string; title: string; body?: ReactNode; tone?: '' | 'warn' | 'fail' | 'live' | 'skip'; steps: Step[] }

const WHO: Record<string, string> = {
  new_business: 'A new customer', general_question: 'Someone with a question', existing_client: 'An existing client',
  job_applicant: 'Someone looking for a job', vendor_or_partnership: 'A business offering a partnership', spam: 'This looks like spam',
}

function out<T>(step: Step | undefined): T {
  return (step?.output ?? {}) as T
}

/** The run's steps, retold as what the assistant did, in the order it did it. */
function buildStory(run: RunDetail, approval: Approval | null): StoryItem[] {
  const by = (id: string) => run.steps.find((s) => s.node_id === id)
  const items: StoryItem[] = []
  const channel = String(run.input.channel ?? '')
  const live = (s: Step | undefined): StoryItem['tone'] => (s?.status === 'running' ? 'live' : s?.status === 'failed' ? 'fail' : '')

  const intake = by('intake')
  if (intake) items.push({ key: 'intake', icon: '📨', title: `Received a message by ${channelLabel(channel).toLowerCase()}`, steps: [intake], tone: live(intake),
    body: run.input.subject ? <>Subject: “{String(run.input.subject)}”</> : undefined })

  const classify = by('classify')
  if (classify) {
    const c = out<{ intent?: string; language?: string; asks_price?: boolean; wants_unoffered_service?: boolean }>(classify)
    const extra = [c.asks_price && 'They asked about prices.', c.wants_unoffered_service && "They want something you don't offer."].filter(Boolean).join(' ')
    items.push({ key: 'classify', icon: '💬', title: classify.status === 'running' ? 'Reading the message…' : 'Understood the message', steps: [classify], tone: live(classify),
      body: c.intent ? <>{WHO[c.intent] ?? 'Someone'}{c.intent === 'spam' ? '.' : `, writing in ${language(c.language)}.`} {extra}</> : undefined })
  }

  const save = by('save_lead')
  if (out<{ status?: string }>(save).status === 'spam') {
    items.push({ key: 'spam', icon: '🚫', title: 'Recognised it as spam', body: 'So no reply was sent and nothing was saved as a lead.', steps: save ? [save] : [], tone: 'skip' })
    return items
  }

  const retrieve = by('retrieve')
  if (retrieve) {
    const passages = out<{ passages?: { id: string; label: string }[] }>(retrieve).passages ?? []
    items.push({ key: 'retrieve', icon: '📖', title: 'Found the right info on your website', steps: [retrieve], tone: live(retrieve),
      body: <div className="chips" style={{ marginTop: 6 }}>{passages.map((p) => <span key={p.id} className="tag">{p.label}</span>)}</div> })
  }

  const qualify = by('qualify')
  if (qualify) {
    const q = out<{ extracted?: { monthly_budget_pkr?: number | null; timeline?: string | null; wants_call?: boolean; business_type?: string | null }; temperature?: string; budget_band?: string }>(qualify)
    if (qualify.status === 'skipped') {
      items.push({ key: 'qualify', icon: '⭐', title: 'Not a sales enquiry', body: 'So it wasn’t scored as a lead.', steps: [qualify], tone: 'skip' })
    } else {
      const e = q.extracted ?? {}
      const parts = [
        e.monthly_budget_pkr ? `budget of ${rupees(e.monthly_budget_pkr)} a month` : q.budget_band && q.budget_band !== 'unknown' ? `budget ${BANDS[q.budget_band]}` : null,
        e.timeline ? `wants to start ${e.timeline}` : null,
        e.wants_call ? 'wants a call' : null,
      ].filter(Boolean)
      const title = { hot: 'Spotted a hot lead', warm: 'A promising lead', cold: 'An early-stage lead' }[q.temperature ?? ''] ?? 'Scored the lead'
      items.push({ key: 'qualify', icon: '⭐', title: qualify.status === 'running' ? 'Scoring the lead…' : title, steps: [qualify], tone: live(qualify),
        body: parts.length ? <>{parts.join(', ').replace(/^./, (x) => x.toUpperCase())}.</> : e.business_type ? <>A {e.business_type}.</> : undefined })
    }
  }

  const draft = by('draft')
  if (draft) items.push({ key: 'draft', icon: '✍️', title: draft.status === 'running' ? 'Writing a reply…' : `Wrote a reply in ${language(String(out<{ language?: string }>(by('classify')).language ?? ''))}`,
    body: 'Using only facts from your website.', steps: [draft], tone: live(draft) })

  const score = by('score')
  if (score) {
    const s = out<{ claims?: Claim[]; route?: string; reasons?: string[] }>(score)
    const claims = (s.claims ?? []).filter((c) => CHECKED_KINDS.has(c.kind))
    items.push({
      key: 'score', icon: '🔍', title: score.status === 'running' ? 'Checking every fact…' : 'Double-checked every fact', steps: [score],
      tone: score.status === 'running' ? 'live' : s.route === 'review' ? 'warn' : live(score),
      body: score.status === 'running' ? undefined : (
        <>
          {claims.length === 0 && <div>No facts to check: the reply only answers what they asked.</div>}
          {claims.map((c, i) => (
            <div key={i} className="fact"><span className={c.supported ? 'y' : 'n'}>{c.supported ? '✓' : '✗'}</span>
              <span dir="auto">“{c.text}” <span className="faint">{c.supported ? 'matches your website' : "isn't on your website"}</span></span></div>
          ))}
          {s.route === 'review' && <div className="notice" style={{ marginTop: 8 }}>So it held the reply for you to check.</div>}
          {s.route === 'auto' && claims.length > 0 && <div className="faint" style={{ marginTop: 6 }}>Everything checks out.</div>}
        </>
      ),
    })
  }

  const approvalStep = by('approval')
  if (approvalStep) {
    if (approvalStep.status === 'waiting') {
      items.push({ key: 'approval', icon: '🙋', title: 'Asked you first', steps: [approvalStep], tone: 'warn',
        body: (
          <>
            {(approval?.payload.reasons ?? []).map((r) => <div key={r}>{friendlyReason(r)}</div>)}
            {approval && <Link className="btn primary small" style={{ marginTop: 10 }} to={`/needs-you/${approval.id}`}>Review the reply</Link>}
          </>
        ) })
    } else {
      const decision = out<{ decision?: string }>(approvalStep).decision ?? approval?.status
      const title = decision === 'edited' ? 'You edited the reply and sent it' : decision === 'rejected' ? 'You chose not to reply' : 'You approved the reply'
      items.push({ key: 'approval', icon: '🙋', title, steps: [approvalStep], tone: decision === 'rejected' ? 'skip' : '' })
    }
  }

  const send = by('send')
  if (send) {
    const d = out<{ mode?: string; to?: string; note?: string }>(send)
    const own = !approvalStep
    let title = own ? 'Sent it, without bothering you' : 'Sent it'
    let body: ReactNode = d.to ? <>By email to {d.to}.</> : undefined
    if (d.mode === 'dry_run') {
      if (channel === 'web_chat') { title = own ? 'Answered in the chat, on its own' : 'Answered in the chat'; body = 'Shown to the customer in the website chat.' }
      else { title = own ? 'Reply ready, on its own' : 'Reply ready'; body = 'Test mode is on, so it wasn’t actually emailed.' }
    }
    if (send.status === 'failed') { title = "Couldn't send the reply"; body = send.error }
    items.push({ key: 'send', icon: '📤', title, body, steps: [send], tone: live(send) })
  }

  const failed = run.steps.find((s) => s.status === 'failed' && !items.some((i) => i.steps.includes(s)))
  if (failed) items.push({ key: 'failed', icon: '⚠️', title: 'Something went wrong here', body: failed.error, steps: [failed], tone: 'fail' })
  return items
}

function techLine(steps: Step[]): string {
  return steps.map((s) => {
    const tokens = s.prompt_tokens + s.completion_tokens
    return [s.node_id, s.model, s.status === 'waiting' ? 'waiting for a person' : duration(s.duration_ms),
      tokens ? `${s.prompt_tokens} → ${s.completion_tokens} tokens` : null, s.cost_usd ? usd(s.cost_usd) : null,
      s.attempts > 1 ? `${s.attempts} attempts` : null].filter(Boolean).join(' · ')
  }).join('\n')
}

function Chat({ run, lead, approval, showReply }: { run: RunDetail; lead: Lead | null; approval: Approval | null; showReply: boolean }) {
  const name = String(run.input.name ?? '') || String(run.input.contact)
  const channel = String(run.input.channel ?? '')
  const draft = out<{ reply?: string }>(run.steps.find((s) => s.node_id === 'draft')).reply
  const reply = approval?.final_payload?.reply ?? lead?.reply ?? draft
  const time = (v: string | null | undefined) => (v ? parseDate(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '')
  const active = run.status === 'queued' || run.status === 'running'
  const spam = lead?.status === 'spam'
  const delivery = out<{ mode?: string }>(run.steps.find((s) => s.node_id === 'send')).mode
  const testMode = delivery === 'dry_run' && channel !== 'web_chat'

  let replyBubble: ReactNode = null
  if (showReply && reply && !spam) {
    if (lead?.status === 'replied') {
      replyBubble = <div className="bubble out" dir="auto">{reply}<div className="meta">{time(run.finished_at)} · {testMode ? 'test mode: not emailed' : approval ? 'sent after your OK' : 'sent by your assistant'}{channel === 'web_chat' ? ' · in the website chat' : ''}</div></div>
    } else if (lead?.status === 'rejected') {
      replyBubble = <div className="bubble out draft" dir="auto">{reply}<div className="meta">Not sent: you chose not to reply</div></div>
    } else if (lead?.status === 'awaiting_approval') {
      replyBubble = <div className="bubble out draft" dir="auto">{reply}<div className="meta">Draft, waiting for your OK</div></div>
    }
  }

  return (
    <div className="phone">
      <div className="phone-head">
        <Avatar name={name} size="lg" />
        <div><b>{name}</b><div className="faint">{channelLabel(channel)}{lead?.language ? ` · ${language(lead.language)}` : ''} · {time(run.created_at)}</div></div>
      </div>
      <div className="bubble in" dir="auto">{String(run.input.message ?? '')}<div className="meta">{time(run.created_at)}</div></div>
      {(active || !showReply) && !spam && <div className="typing">Your assistant is working on a reply<i /><i /><i /></div>}
      {replyBubble}
      {spam && showReply && <div className="faint" style={{ textAlign: 'center' }}>No reply: this was spam.</div>}
    </div>
  )
}

export default function Conversation() {
  const { runId = '' } = useParams()
  const { on: tech } = useTech()
  const queryClient = useQueryClient()
  const isLive = (status?: string) => status === 'queued' || status === 'running'
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(runId),
    refetchInterval: (q) => (isLive(q.state.data?.status) ? 1000 : q.state.data?.status === 'waiting_approval' ? 5000 : false) })
  const convo = useQuery({ queryKey: ['conversation', runId], queryFn: () => api.conversation(runId),
    refetchInterval: () => (isLive(run.data?.status) || run.data?.status === 'waiting_approval' ? 1500 : false) })
  const automation = useQuery({ queryKey: ['automation', 'lead_handler'], queryFn: () => api.automation('lead_handler'), enabled: tech })
  const retry = useMutation({ mutationFn: () => api.retryRun(runId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', runId] }) })
  const [revealed, setRevealed] = useState<number | null>(null)  // null = show everything; a number = replaying
  const [selected, setSelected] = useState<string | null>(null)

  const r = run.data
  const lead = convo.data?.lead ?? null
  const approval = convo.data?.approval ?? null
  const story = useMemo(() => (r ? buildStory(r, approval) : []), [r, approval])

  useEffect(() => {
    if (revealed === null) return
    if (revealed >= story.length) { const t = setTimeout(() => setRevealed(null), 600); return () => clearTimeout(t) }
    const t = setTimeout(() => setRevealed((n) => (n === null ? null : n + 1)), 850)
    return () => clearTimeout(t)
  }, [revealed, story.length])

  if (run.error) return <ErrorBox error={run.error} />
  if (!r) return <div className="card empty">Loading…</div>

  const shown = revealed === null ? story : story.slice(0, revealed)
  const replyRevealed = revealed === null || shown.some((s) => s.key === 'send' || s.key === 'approval')
  const st = statusText(lead, r.status)
  const systemMs = r.steps.reduce((sum, s) => sum + (s.status === 'waiting' ? 0 : s.duration_ms), 0)
  const autoSent = lead?.status === 'replied' && !approval
  const name = String(r.input.name ?? '') || String(r.input.contact)
  const reasons = scoreReasons(lead?.score_reasons)
  const step = nextStep(lead, approval)
  const canEmail = String(r.input.contact).includes('@')
  const ringColor = lead?.temperature === 'hot' ? '#0A4174' : lead?.temperature === 'warm' ? '#4E8EA2' : '#7BBDE8'

  return (
    <>
      <div className="page-head">
        <div>
          <div className="crumbs"><Link to="/conversations">← Conversations</Link></div>
          <div className="row" style={{ gap: 12 }}>
            <h1>{name}{lead?.business_type ? ` · ${lead.business_type}` : ''}</h1>
            <span className={`chip ${st.tone}`}>{autoSent ? `✓ Replied on its own in ${Math.max(1, Math.round(systemMs / 1000))} sec` : st.text}</span>
          </div>
        </div>
        <div className="row">
          {r.status === 'failed' && <button className="btn primary" onClick={() => retry.mutate()} disabled={retry.isPending}>Try again</button>}
          <button className="btn" disabled={isLive(r.status) || revealed !== null} onClick={() => setRevealed(0)}>▶ Replay how it happened</button>
        </div>
      </div>
      <ErrorBox error={retry.error} />

      <div className="xray-grid">
        <div className="stack" style={{ gap: 10, minWidth: 0 }}>
          <h3>The conversation</h3>
          <Chat run={r} lead={lead} approval={approval} showReply={replyRevealed} />
        </div>

        <div className="stack" style={{ gap: 10, minWidth: 0 }}>
          <h3>How your assistant handled it</h3>
          <div className="card story">
            {shown.map((item) => (
              <div key={item.key} className={`st ${item.tone ?? ''}`}>
                <div className="dot">{item.icon}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="t">{item.title}</div>
                  {item.body && <div className="b">{item.body}</div>}
                  {tech && item.steps.length > 0 && (
                    <>
                      <div className="tech-line" style={{ whiteSpace: 'pre-line' }}>{techLine(item.steps)}</div>
                      <details className="raw"><summary>raw input / output</summary>
                        {item.steps.map((s) => <pre key={s.node_id} className="code" dir="auto">{json({ input: s.input, output: s.output, error: s.error })}</pre>)}
                      </details>
                    </>
                  )}
                </div>
              </div>
            ))}
            {isLive(r.status) && revealed === null && <div className="faint">Working… this page updates by itself.</div>}
          </div>
          {tech && automation.data && (
            <section className="card" aria-label="Run graph">
              <div className="card-head"><h2>Run graph</h2><span className="spacer" /><span className="faint mono">{r.id.slice(0, 8)} · click a node</span></div>
              <FlowGraph automation={automation.data} steps={r.steps} runActive={isLive(r.status)} selected={selected} onSelect={setSelected} compact />
            </section>
          )}
        </div>

        <div className="stack" style={{ gap: 14, minWidth: 0 }}>
          {lead?.temperature && lead.temperature !== 'not_a_lead' ? (
            <div className="card pad">
              <h3 style={{ marginBottom: 12 }}>Lead quality</h3>
              <div className="row" style={{ gap: 16, flexWrap: 'nowrap' }}>
                <div className="ring" style={{ background: `conic-gradient(${ringColor} 0 ${lead.score ?? 0}%, #BDD8E9 ${lead.score ?? 0}% 100%)` }}><div>{lead.score}</div></div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>{lead.temperature[0].toUpperCase() + lead.temperature.slice(1)} lead</div>
                  <span className={`chip ${lead.temperature}`}>{{ hot: 'Worth calling today', warm: 'Worth a follow-up', cold: 'Early stage' }[lead.temperature]}</span>
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                {reasons.map((x) => <div key={x.text} className="reason-row"><span>{x.text}</span><b>{x.points}</b></div>)}
              </div>
            </div>
          ) : lead ? (
            <div className="card pad"><h3 style={{ marginBottom: 8 }}>Lead quality</h3><p className="muted">{lead.status === 'spam' ? 'Spam: not a lead.' : 'Not a sales enquiry, so it isn’t scored.'}</p></div>
          ) : null}

          {step && (
            <div className="card dark pad stack" style={{ gap: 12 }}>
              <h3>Suggested next step</h3>
              <p style={{ fontSize: 15, fontWeight: 600 }}>{step}</p>
              <div className="row">
                {approval?.status === 'pending' && <Link className="btn light" to={`/needs-you/${approval.id}`}>Review the reply</Link>}
                {canEmail && <a className="btn ghost-dark" href={`mailto:${String(r.input.contact)}`}>Reply myself</a>}
              </div>
            </div>
          )}

          {tech && (
            <div className="card pad">
              <h3 style={{ marginBottom: 8 }}>Run trace</h3>
              <div className="trace-row">run<b>{r.id.slice(0, 8)}</b></div>
              <div className="trace-row">status<b>{r.status}</b></div>
              <div className="trace-row">system time<b>{duration(systemMs)}</b></div>
              <div className="trace-row">tokens<b>{r.total_tokens.toLocaleString()}</b></div>
              <div className="trace-row">cost<b>{usd(r.total_cost_usd)}</b></div>
              <div className="trace-row">retries<b>{r.steps.reduce((n, s) => n + Math.max(0, s.attempts - 1), 0)}</b></div>
              <div className="trace-row">models<b>{[...new Set(r.steps.map((s) => s.model).filter(Boolean))].map((m) => String(m).split('/').pop()).join(', ') || '—'}</b></div>
              <Link to={`/runs/${r.id}`} className="faint mono">full run view →</Link>
            </div>
          )}
          <p className="faint" style={{ padding: '0 4px' }}>This conversation cost about <b style={{ color: 'var(--text)' }}>{rupeesFromUsd(r.total_cost_usd)}</b> in AI.</p>
        </div>
      </div>
    </>
  )
}
