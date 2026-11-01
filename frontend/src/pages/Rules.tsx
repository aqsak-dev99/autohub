import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Rules } from '../api'
import { ErrorBox } from '../components/ui'
import { LANGUAGES } from '../format'
import { useTech } from '../tech'

const LANGS = ['english', 'roman_urdu', 'urdu', 'arabic']

function sureness(v: number): string {
  if (v >= 0.95) return 'Only when every fact checks out'
  if (v >= 0.8) return 'When almost every fact checks out'
  if (v >= 0.65) return 'When most facts check out'
  return 'Whenever it can'
}

export default function RulesPage() {
  const { on: tech } = useTech()
  const queryClient = useQueryClient()
  const saved = useQuery({ queryKey: ['rules'], queryFn: api.rules })
  const [draft, setDraft] = useState<Rules | null>(null)
  useEffect(() => { if (saved.data && !draft) setDraft(saved.data) }, [saved.data, draft])

  // "what if": replay last week's replies under the rules on screen (pure code on the server, instant)
  const [debounced, setDebounced] = useState<Rules | null>(null)
  useEffect(() => { const t = setTimeout(() => setDebounced(draft), 300); return () => clearTimeout(t) }, [draft])
  const preview = useQuery({ queryKey: ['rulesPreview', debounced], queryFn: () => api.previewRules(debounced!), enabled: !!debounced })

  const save = useMutation({
    mutationFn: () => api.saveRules(draft!),
    onSuccess: (r) => { queryClient.setQueryData(['rules'], r); setDraft(r) },
  })

  if (!draft) return <><ErrorBox error={saved.error} /><div className="card empty">Loading…</div></>
  const changed = JSON.stringify(draft) !== JSON.stringify(saved.data)
  const set = (patch: Partial<Rules>) => setDraft({ ...draft, ...patch })
  const toggleLang = (l: string) => set({ review_languages: draft.review_languages.includes(l) ? draft.review_languages.filter((x) => x !== l) : [...draft.review_languages, l] })
  const p = preview.data
  const delta = p ? p.review_now - p.review_with_rules : 0

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Your rules</h1>
          <div className="sub">Decide when your assistant may reply on its own, and when it should ask you first. Changes apply to the next message.</div>
        </div>
        <div className="row">
          {changed && <button className="btn" onClick={() => setDraft(saved.data!)}>Undo changes</button>}
          <button className="btn primary" disabled={!changed || save.isPending} onClick={() => save.mutate()}>{save.isSuccess && !changed ? 'Saved ✓' : 'Save rules'}</button>
        </div>
      </div>
      <ErrorBox error={save.error || preview.error} />

      <div className="home-grid">
        <div className="stack" style={{ gap: 14 }}>
          <div className="card rule-box">
            <div className="rule-q">How sure must it be to reply without you?</div>
            <div className="muted" style={{ fontSize: 13.5 }}>{sureness(draft.auto_send_confidence)}.</div>
            <input className="range" type="range" min={0.5} max={1} step={0.05} value={draft.auto_send_confidence}
              onChange={(e) => set({ auto_send_confidence: Number(e.target.value) })} aria-label="How sure it must be" />
            <div className="ends"><span>Reply whenever it can</span><span>Only when every fact checks out</span></div>
            {tech && <div className="tech-line">auto_send_confidence = {draft.auto_send_confidence.toFixed(2)} (share of checked claims supported by the knowledge base)</div>}
          </div>

          <div className="card rule-box">
            <div className="rule-q">Always ask me first when the reply is in</div>
            <div className="muted" style={{ fontSize: 13.5, marginBottom: 12 }}>Useful for languages you want to keep an eye on.</div>
            <div className="chips">
              {LANGS.map((l) => (
                <button key={l} className="pill" aria-pressed={draft.review_languages.includes(l)} onClick={() => toggleLang(l)}>
                  {LANGUAGES[l]}{draft.review_languages.includes(l) ? ' ✓' : ''}
                </button>
              ))}
            </div>
          </div>

          <div className="card rule-box">
            <div className="rule-q">…or when a customer</div>
            {([
              ['review_price_not_on_site', 'Gets a price that isn’t on my website'],
              ['review_existing_client', 'Is already my client'],
              ['review_unoffered_service', 'Wants a service I don’t offer'],
            ] as const).map(([key, label]) => (
              <div key={key} className="toggle-row">
                <span>{label}</span>
                <button className="switch on-light" role="switch" aria-checked={draft[key]} aria-label={label} onClick={() => set({ [key]: !draft[key] } as Partial<Rules>)}>
                  <span className="track" />
                </button>
              </div>
            ))}
          </div>

          <div className="card rule-box">
            <div className="rule-q">Always, whatever the rules</div>
            <div className="toggle-row"><span>A reply with a fact or promise that isn’t on my website comes to me</span><span className="lock">🔒 always on</span></div>
            <div className="toggle-row"><span>A reply in a different language from the customer’s comes to me</span><span className="lock">🔒 always on</span></div>
            <div className="toggle-row"><span>A message in a language it doesn’t handle yet comes to me</span><span className="lock">🔒 always on</span></div>
            <div className="faint" style={{ marginTop: 6 }}>These are the ways an AI reply can go wrong without anyone noticing, so they can’t be switched off.</div>
          </div>
        </div>

        <aside className="stack" style={{ gap: 14 }}>
          <div className="whatif">
            <h3 style={{ color: 'var(--steel-500)' }}>If these rules had been on last week</h3>
            {!p ? <div className="faint" style={{ marginTop: 8 }}>Working it out…</div> : p.replies === 0 ? (
              <div className="muted" style={{ marginTop: 8 }}>No replies in the last 7 days to compare with yet. Send a few test messages first.</div>
            ) : (
              <>
                <div className="big">
                  {delta > 0 && <><b>{delta} more</b> customer{delta === 1 ? '' : 's'} would have got an instant reply</>}
                  {delta < 0 && <><b>{-delta} more</b> repl{delta === -1 ? 'y' : 'ies'} would have come to you first</>}
                  {delta === 0 && <><b>No change</b> for last week’s {p.replies} replies</>}
                </div>
                <div className="muted" style={{ fontSize: 13.5 }}>
                  {p.review_with_rules} of {p.replies} replies would have needed you (now {p.review_now}).
                  {delta > 0 && ' None of them had a fact that wasn’t on your website.'}
                </div>
                {p.would_send_on_its_own.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="faint">Would now reply on its own:</div>
                    <div className="chips" style={{ marginTop: 4 }}>
                      {p.would_send_on_its_own.slice(0, 8).map((x) => <Link key={x.run_id} to={`/conversations/${x.run_id}`} className="tag">{x.name}</Link>)}
                    </div>
                  </div>
                )}
                {p.would_ask_you.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="faint">Would now come to you:</div>
                    <div className="chips" style={{ marginTop: 4 }}>
                      {p.would_ask_you.slice(0, 8).map((x) => <Link key={x.run_id} to={`/conversations/${x.run_id}`} className="tag">{x.name}</Link>)}
                    </div>
                  </div>
                )}
              </>
            )}
            {tech && p && <div className="tech-line">replayed lead_handler.route_reply over {p.replies} recorded runs ({p.days}d) · no LLM calls</div>}
          </div>
          <div className="card pad">
            <h3 style={{ marginBottom: 6 }}>How this works</h3>
            <p className="muted" style={{ fontSize: 13.5 }}>
              Your assistant writes every reply, then checks each fact against your website. These rules only decide who presses send:
              your assistant, or you. Whatever you choose, nothing goes out with a fact your website doesn’t back up.
            </p>
          </div>
        </aside>
      </div>
    </>
  )
}
