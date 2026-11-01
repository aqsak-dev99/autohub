import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { api } from './api'
import { TechSwitch } from './components/ui'
import { BUSINESS_NAME, OWNER_NAME } from './config'
import AutomationDetailPage from './pages/AutomationDetail'
import Automations from './pages/Automations'
import Conversation from './pages/Conversation'
import Conversations from './pages/Conversations'
import Home from './pages/Home'
import Leads from './pages/Leads'
import NeedsYou from './pages/NeedsYou'
import RulesPage from './pages/Rules'
import RunDetailPage from './pages/RunDetail'
import Runs from './pages/Runs'
import { useTech } from './tech'

// old links (/approvals/7) keep working
function ApprovalRedirect() {
  const { id } = useParams()
  return <Navigate to={id ? `/needs-you/${id}` : '/needs-you'} replace />
}

export default function App() {
  const { on: tech } = useTech()
  // the "Needs you" count stays current on every page
  const pending = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => api.approvals('pending'), refetchInterval: 5000 })
  const count = pending.data?.length ?? 0

  return (
    <>
      <header className="top">
        <Link to="/" className="brand"><span className="brand-mark">✦</span>AutoHub <small>· {BUSINESS_NAME}</small></Link>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/conversations">Conversations</NavLink>
          <NavLink to="/needs-you">Needs you{count > 0 && <span className="count">{count}</span>}</NavLink>
          <NavLink to="/leads">Leads</NavLink>
          <NavLink to="/rules">Rules</NavLink>
          {tech && <NavLink to="/runs" className="tech-link">runs</NavLink>}
          {tech && <NavLink to="/automations" className="tech-link">automations</NavLink>}
        </nav>
        <div className="top-right">
          <TechSwitch />
          <span className="me" title={OWNER_NAME}>{OWNER_NAME[0]}</span>
        </div>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/conversations" element={<Conversations />} />
          <Route path="/conversations/:runId" element={<Conversation />} />
          <Route path="/needs-you" element={<NeedsYou />} />
          <Route path="/needs-you/:id" element={<NeedsYou />} />
          <Route path="/approvals/:id?" element={<ApprovalRedirect />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/automations" element={<Automations />} />
          <Route path="/automations/:slug" element={<AutomationDetailPage />} />
          <Route path="*" element={<div className="card empty">Page not found. <Link to="/">Go home</Link></div>} />
        </Routes>
      </main>
    </>
  )
}
