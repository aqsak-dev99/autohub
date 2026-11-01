import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ErrorBox } from './ui'

const EXAMPLES = [
  { label: 'English', name: 'Zainab', text: 'Hi, I run a bakery in Gulberg. How much would Instagram posts every month cost?' },
  { label: 'Roman Urdu', name: 'Usman', text: 'Salam, mera clothing brand hai, ads chalwane hain. Budget 2 lakh mahana hai, kitna kharcha hoga?' },
  { label: 'Urdu', name: 'Sana', text: 'السلام علیکم، مجھے اپنے ریسٹورنٹ کے لیے انسٹاگرام مارکیٹنگ چاہیے۔ آپ کی فیس کیا ہے؟' },
  { label: 'Arabic', name: 'Khalid', text: 'مرحبا، نحن متجر عطور في دبي ونرغب في إعلانات على إنستغرام. كم التكلفة؟' },
  { label: 'Not offered', name: 'Fahad', text: 'Can you build a mobile app for our gym?' },
]

/** "Try it": the owner (or an interviewer) plays a customer and watches the assistant answer live. */
export function TryIt({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [name, setName] = useState(EXAMPLES[0].name)
  const [message, setMessage] = useState(EXAMPLES[0].text)
  const send = useMutation({
    mutationFn: () => api.testMessage(message, name || undefined),
    onSuccess: (r) => { onClose(); navigate(`/conversations/${r.run_id}`) },
  })
  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="try-title" onClick={(e) => e.stopPropagation()}>
        <div>
          <h2 id="try-title">Try it: write as a customer</h2>
          <p className="muted" style={{ marginTop: 4 }}>Your assistant answers in a few seconds and you watch every step. Nothing is emailed to anyone.</p>
        </div>
        <div className="examples" aria-label="Examples">
          {EXAMPLES.map((ex) => (
            <button key={ex.label} onClick={() => { setName(ex.name); setMessage(ex.text) }}>{ex.label}</button>
          ))}
        </div>
        <label className="lbl" htmlFor="try-name">Customer name</label>
        <input id="try-name" className="field" value={name} onChange={(e) => setName(e.target.value)} />
        <label className="lbl" htmlFor="try-msg">Message</label>
        <textarea id="try-msg" className="field" rows={4} dir="auto" value={message} onChange={(e) => setMessage(e.target.value)} />
        <ErrorBox error={send.error} />
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={message.trim().length < 2 || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? 'Sending…' : 'Send and watch'}
          </button>
        </div>
      </div>
    </div>
  )
}
