import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

/**
 * "Technical details": one switch for the whole app. Off, AutoHub talks like a business tool
 * (customers, replies, rupees). On, every screen also shows the engineering underneath:
 * models, tokens, latency, raw step input and output, run graphs and heatmaps.
 */
type Tech = { on: boolean; toggle: () => void }
const TechContext = createContext<Tech>({ on: false, toggle: () => {} })
const KEY = 'autohub.technical'

function readSaved(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false // private windows can block storage; just start in simple mode
  }
}

export function TechProvider({ children }: { children: ReactNode }) {
  const [on, setOn] = useState(readSaved)
  useEffect(() => {
    try {
      localStorage.setItem(KEY, on ? '1' : '0')
    } catch {
      /* not saved; fine */
    }
  }, [on])
  return <TechContext.Provider value={{ on, toggle: () => setOn((v) => !v) }}>{children}</TechContext.Provider>
}

export const useTech = () => useContext(TechContext)
