import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { LineArt } from '../components/LineArt'
import { ErrorBox } from '../components/ui'
import { BUSINESS_NAME } from '../config'

/** The front door: the owner logs in; anyone else can explore the demo without a password. */
export default function Login() {
  const { me, refresh } = useAuth()
  const [password, setPassword] = useState('')
  const login = useMutation({ mutationFn: () => api.login(password), onSuccess: refresh })
  const demo = useMutation({ mutationFn: api.demo, onSuccess: refresh })
  const submit = (e: FormEvent) => { e.preventDefault(); if (password) login.mutate() }

  return (
    <div className="login">
      <section className="login-form">
        <div className="brand"><span className="brand-mark">✦</span>AutoHub <small>· {BUSINESS_NAME}</small></div>
        <div className="login-form-inner">
          <div>
            <h1>Welcome to AutoHub</h1>
            <p className="muted" style={{ marginTop: 6 }}>{BUSINESS_NAME}’s AI assistant: it answers every customer in seconds, and asks you when it isn’t sure.</p>
          </div>
          {me?.demo_available && (
            <>
              <button className="btn primary" style={{ height: 46, fontSize: 15 }} disabled={demo.isPending} onClick={() => demo.mutate()}>
                Explore the demo →
              </button>
              <p className="faint" style={{ marginTop: -6 }}>Sample conversations, plus “Try it” to write as a customer yourself. No sign-up.</p>
              <ErrorBox error={demo.error} />
              <div className="or"><span>or log in as the owner</span></div>
            </>
          )}
          <form className="stack" style={{ gap: 10 }} onSubmit={submit}>
            {!me?.demo_available && <h2>Owner login</h2>}
            <label className="lbl" htmlFor="pw">Password</label>
            <input id="pw" className="field" type="password" placeholder="••••••••" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <ErrorBox error={login.error} />
            <button className="btn" type="submit" style={{ height: 44 }} disabled={!password || login.isPending}>Log in</button>
          </form>
        </div>
        <p className="foot">A portfolio project · FastAPI · Groq · React Flow</p>
      </section>
      <section className="login-art" aria-hidden>
        <LineArt />
        <div className="mark"><span className="star">✦</span>AutoHub</div>
        <div className="points">
          <span>English · Roman Urdu · Urdu · Arabic</span>
          <span>Every fact checked</span>
          <span>You approve what it isn’t sure about</span>
        </div>
      </section>
    </div>
  )
}
