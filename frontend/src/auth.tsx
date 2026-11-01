import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { api, type Me } from './api'

/**
 * Who is using the dashboard. With login switched off (local development) everyone is the owner.
 * On the public demo, a visitor is a "viewer": they can look at everything and use Try it,
 * and the screens explain the few things only the owner can do.
 */
type Auth = { me: Me | undefined; loading: boolean; isViewer: boolean; refresh: () => void }
const AuthContext = createContext<Auth>({ me: undefined, loading: true, isViewer: false, refresh: () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: 60_000, retry: 0 })
  const refresh = () => {
    queryClient.invalidateQueries()  // a different person may see different things: refetch everything
  }
  useEffect(() => {
    const onLoggedOut = () => queryClient.invalidateQueries({ queryKey: ['me'] })
    window.addEventListener('autohub:logged-out', onLoggedOut)
    return () => window.removeEventListener('autohub:logged-out', onLoggedOut)
  }, [queryClient])
  return (
    <AuthContext.Provider value={{ me: me.data, loading: me.isLoading, isViewer: me.data?.role === 'viewer', refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)

/** Test messages from "Try it" are the only replies a demo visitor may approve. */
export const TEST_CONTACT = 'dashboard-test'
