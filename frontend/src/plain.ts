// Turning what the system records into sentences a business owner reads naturally.
import type { Approval, Lead } from './api'
import { BUSINESS_NAME, PKR_PER_USD } from './config'
import { LANGUAGES, SERVICES } from './format'

export const CHANNEL: Record<string, { label: string; icon: string; color: string }> = {
  email: { label: 'Email', icon: '@', color: '#216A85' },
  web_form: { label: 'Website form', icon: '⌂', color: '#3E88A6' },
  web_chat: { label: 'Website chat', icon: '💬', color: '#185670' },
}
export const channelLabel = (c: string | null | undefined) => (c && CHANNEL[c]?.label) || c || '—'

export const language = (l: string | null | undefined) => (l && LANGUAGES[l]) || 'an unknown language'

export function rupeesFromUsd(usd: number | null | undefined): string {
  if (!usd) return 'Rs 0'
  const rs = usd * PKR_PER_USD
  if (rs < 1) return `Rs ${rs.toFixed(2)}`
  return `Rs ${Math.round(rs).toLocaleString('en-PK')}`
}

/** Why a reply was held, said the way an owner would say it. */
export function friendlyReason(reason: string): string {
  const r = reason.toLowerCase()
  if (r.startsWith('confidence')) return "It wasn't sure enough about this reply."
  if (r.startsWith('unsupported claims')) {
    const what = reason.split(':').slice(1).join(':').trim()
    return what && !what.startsWith('reply not supported') ? `It wrote something that isn't on your website: “${what}”.` : "Part of the reply isn't backed by your website."
  }
  if (r.includes("language doesn't match")) return "The reply came out in a different language from the customer's."
  if (r.includes("doesn't support yet")) return "The customer wrote in a language it doesn't handle yet."
  if (r.includes('replies are reviewed')) {
    const lang = reason.split(' replies')[0].replace('Urdu-script', 'Urdu')
    return `You asked to check ${lang} replies before they go out.`
  }
  if (r.startsWith('price not in knowledge base')) return `It mentioned a price that isn't on your website (${reason.split(':')[1]?.trim()}).`
  if (r.startsWith('existing client')) return 'This is an existing client, and you handle clients personally.'
  if (r.includes("service flowpath doesn't offer")) return "They want something you don't offer."
  return reason
}

export function statusText(lead: Lead | null, runStatus?: string): { text: string; tone: 'ok' | 'wait' | 'fail' | 'run' | 'muted' } {
  if (runStatus === 'queued' || runStatus === 'running') return { text: 'Working on it…', tone: 'run' }
  if (runStatus === 'failed' || lead?.status === 'failed') return { text: 'Something went wrong', tone: 'fail' }
  switch (lead?.status) {
    case 'replied': return { text: 'Replied', tone: 'ok' }
    case 'awaiting_approval': return { text: 'Waiting for you', tone: 'wait' }
    case 'rejected': return { text: 'You chose not to reply', tone: 'muted' }
    case 'spam': return { text: 'Spam, ignored', tone: 'muted' }
    default: return { text: 'New', tone: 'run' }
  }
}

export function wants(lead: Pick<Lead, 'services' | 'intent'>): string {
  if (lead.intent === 'job_applicant') return 'Looking for a job'
  if (lead.intent === 'existing_client') return 'Existing client'
  if (lead.intent === 'vendor_or_partnership') return 'Partnership offer'
  if (lead.intent === 'spam') return 'Spam'
  const s = (lead.services ?? []).map((x) => SERVICES[x] ?? x)
  return s.length ? s.join(' + ') : lead.intent === 'general_question' ? 'A question' : '—'
}

/** Score reasons are written for engineers ("+30 wants to work with flowpath"); reword for the owner. */
export function scoreReasons(reasons: string[] | null | undefined): { points: string; text: string }[] {
  return (reasons ?? []).map((r) => {
    const m = r.match(/^([+-]\d+)\s+(.*)$/)
    let text = (m ? m[2] : r)
      .replace(`wants to work with ${BUSINESS_NAME}`, 'Wants to work with you')
      .replace(/interested in (\d) service\(s\)/, (_, n) => (n === '1' ? 'Wants 1 of your services' : `Wants ${n} of your services`))
      .replace(/^budget /, 'Budget ')
      .replace('high urgency', 'Wants to start soon').replace('normal urgency', 'Has a timeline in mind')
      .replace(/business type known \((.*)\)/, 'You know their business: $1')
      .replace('asked for a call or meeting', 'Asked for a call')
      .replace('asking a general question', 'Asked a general question')
    text = text.charAt(0).toUpperCase() + text.slice(1)
    return { points: m ? m[1] : '', text }
  })
}

/** One suggested action per conversation, so the owner knows what to do next. */
export function nextStep(lead: Lead | null, approval: Approval | null): string | null {
  if (!lead) return null
  const name = lead.name || 'them'
  if (approval?.status === 'pending') return `Check the reply waiting for your OK, then it goes to ${name}.`
  if (lead.status === 'spam') return null
  if (lead.intent === 'existing_client') return `Get back to ${name} yourself. Existing clients expect a person.`
  if (lead.intent === 'job_applicant') return `Forward ${name}'s message to whoever handles hiring.`
  if (lead.status === 'failed') return 'Try the run again, or reply yourself.'
  const asksCall = (lead.score_reasons ?? []).some((r) => r.includes('call'))
  if (lead.temperature === 'hot') return asksCall ? `Call ${name} today. They asked for a call and have a strong budget.` : `Follow up with ${name} today: this is a strong lead.`
  if (lead.temperature === 'warm') return `If ${name} hasn't replied in two days, send a short follow-up.`
  return 'Nothing needed: the reply covers it.'
}

const AVATAR_COLORS = ['#216A85', '#2B7D9C', '#3E88A6', '#185670', '#0E4A61', '#4F95B1']
export function avatarColor(seed: string): string {
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}
export function initials(name: string | null | undefined): string {
  const parts = (name || '?').trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '?') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

export function greeting(now = new Date()): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}
