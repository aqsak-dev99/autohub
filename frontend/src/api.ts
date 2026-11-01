// Types mirror the FastAPI response models; every call goes to /api on the same origin.

export type Automation = {
  id: number
  slug: string
  name: string
  description: string
  trigger: string
  enabled: boolean
}

export type GraphNode = { id: string; type: string; position: { x: number; y: number }; data: { label: string } }
export type GraphEdge = { id: string; source: string; target: string; label?: string }
export type AutomationDetail = Automation & { graph: { nodes: GraphNode[]; edges: GraphEdge[] } }

export type RunStatus = 'queued' | 'running' | 'waiting_approval' | 'succeeded' | 'failed'
export type StepStatus = 'running' | 'succeeded' | 'failed' | 'skipped' | 'waiting'

export type Run = {
  id: string
  automation_id: number
  label: string | null
  status: RunStatus
  total_tokens: number
  total_cost_usd: number
  error: string | null
  created_at: string
  finished_at: string | null
}

export type Step = {
  node_id: string
  position: number
  status: StepStatus
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  error: string | null
  attempts: number
  model: string | null
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  duration_ms: number
  started_at: string
  finished_at: string | null
}

export type RunDetail = Run & { input: Record<string, unknown>; output: Record<string, unknown> | null; steps: Step[] }

export type Passage = { id: string; label: string; url: string; score: number | null; pinned?: boolean }

export type Approval = {
  id: number
  run_id: string
  kind: string
  reason: string
  status: 'pending' | 'approved' | 'edited' | 'rejected'
  created_at: string
  decided_at: string | null
  final_payload: { reply?: string; similarity?: number; note?: string | null } | null
  payload: {
    lead_id: number
    channel: string
    contact: string
    name: string | null
    message: string
    language: string
    intent: string
    reply: string
    confidence: number
    reasons: string[]
    temperature: string
    score: number
    qualification: {
      services: string[]
      business_type: string | null
      monthly_budget_pkr: number | null
      budget_band: string
      timeline: string | null
    }
    passages: Passage[]
    translation?: { message_en: string; reply_en: string } | null
  }
}

export type Lead = {
  id: number
  run_id: string | null
  channel: string
  contact: string
  name: string | null
  message: string
  language: string | null
  intent: string | null
  services: string[] | null
  business_type: string | null
  monthly_budget_pkr: number | null
  budget_band: string | null
  timeline: string | null
  score: number | null
  temperature: string | null
  score_reasons: string[] | null
  confidence: number | null
  reply: string | null
  replied: boolean
  status: string
  created_at: string
}

export type Overview = {
  days: number
  runs: number
  succeeded: number
  failed: number
  waiting: number
  success_rate: number | null
  median_run_seconds: number | null
  cost_usd: number
  tokens: number
  leads: number
  hot_leads: number
  auto_sent_rate: number | null
  edit_rate: number | null
  pending_approvals: number
  series: { date: string; runs: number; failed: number; cost_usd: number }[]
  hot: { id: number; name: string; channel: string; score: number | null; services: string[]; budget_band: string | null; status: string; run_id: string | null }[]
}

export type NodeStat = {
  count: number
  share_of_runs: number
  avg_ms: number | null
  avg_cost_usd: number | null
  failure_rate: number | null
  avg_tokens: number | null
  human: boolean
}
export type NodeStats = { automation: string; days: number; runs: number; nodes: Record<string, NodeStat> }

export type Live = {
  active: { run_id: string; name: string; channel: string | null; node_id: string; status: RunStatus }[]
  today: { received: number; sent_on_its_own: number; asked_you: number; spam: number }
}

export type Rules = {
  auto_send_confidence: number
  review_languages: string[]
  review_price_not_on_site: boolean
  review_existing_client: boolean
  review_unoffered_service: boolean
}

export type RulesPreview = {
  days: number
  replies: number
  review_now: number
  review_with_rules: number
  would_send_on_its_own: { name: string; language: string | null; run_id: string }[]
  would_ask_you: { name: string; language: string | null; run_id: string; reasons: string[] }[]
}

export type Conversation = { lead: Lead | null; approval: Approval | null }

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  automations: () => request<Automation[]>('/api/automations'),
  automation: (slug: string) => request<AutomationDetail>(`/api/automations/${slug}`),
  runs: (params: { automation?: string; status?: string; limit?: number } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && q.set(k, String(v)))
    return request<Run[]>(`/api/runs?${q}`)
  },
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  retryRun: (id: string) => request<Run>(`/api/runs/${id}/retry`, { method: 'POST' }),
  triggerRun: (slug: string, input: Record<string, unknown> = {}) =>
    request<Run & { dispatched_via: string }>(`/api/automations/${slug}/runs`, {
      method: 'POST',
      body: JSON.stringify({ input }),
    }),
  testMessage: (message: string, name?: string) =>
    request<{ run_id: string }>('/api/test-message', { method: 'POST', body: JSON.stringify({ message, name }) }),
  conversation: (runId: string) => request<Conversation>(`/api/conversations/${runId}`),
  live: () => request<Live>('/api/stats/live'),
  rules: () => request<Rules>('/api/rules'),
  saveRules: (rules: Rules) => request<Rules>('/api/rules', { method: 'PUT', body: JSON.stringify(rules) }),
  previewRules: (rules: Rules) => request<RulesPreview>('/api/rules/preview', { method: 'POST', body: JSON.stringify(rules) }),
  approvals: (status = 'pending') => request<Approval[]>(`/api/approvals?status=${status}`),
  decide: (id: number, body: { action: 'approve' | 'edit' | 'reject'; reply?: string; note?: string }) =>
    request<Approval>(`/api/approvals/${id}/decision`, { method: 'POST', body: JSON.stringify(body) }),
  leads: (params: { temperature?: string; status?: string } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v && q.set(k, v))
    return request<Lead[]>(`/api/leads?${q}&limit=200`)
  },
  overview: (days = 7) => request<Overview>(`/api/stats/overview?days=${days}`),
  nodeStats: (slug: string, days = 7) => request<NodeStats>(`/api/stats/automations/${slug}/nodes?days=${days}`),
}
