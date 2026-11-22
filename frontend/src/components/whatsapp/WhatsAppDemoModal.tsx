import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CheckCircle, WhatsappLogo, X } from '@phosphor-icons/react'
import { ApiError, api } from '../../services/api'
import { Button } from '../ui/Button'

interface WhatsAppDemoModalProps {
  open: boolean
  onClose: () => void
}

interface DemoLinkResponse {
  ok: boolean
  join_url: string
}

export function WhatsAppDemoModal({ open, onClose }: WhatsAppDemoModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [phone, setPhone] = useState('')
  const [passcode, setPasscode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DemoLinkResponse | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    if (open) return
    setPhone('')
    setPasscode('')
    setError(null)
    setResult(null)
  }, [open])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const nationalNumber = phone.replace(/\D/g, '').replace(/^0/, '')
      const response = await api<DemoLinkResponse>('/v1/whatsapp/demo-link', {
        method: 'POST',
        body: JSON.stringify({ phone: `+234${nationalNumber}`, passcode }),
      })
      setResult(response)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('We couldn’t verify demo access. Check your details and try again.')
      } else if (err instanceof ApiError && err.status === 422) {
        setError('Enter a valid phone number.')
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Try again in a minute.')
      } else {
        setError('Could not start the demo. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="whatsapp-demo-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-panel bg-white p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm max-sm:mb-0 max-sm:mt-auto max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-panel"
    >
      <div className="p-5 sm:p-7">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-card bg-primary/10 text-primary">
              <WhatsappLogo size={22} weight="fill" aria-hidden="true" />
            </span>
            <div>
              <h2 id="whatsapp-demo-title" className="text-xl font-semibold text-primary">Try it on WhatsApp</h2>
              <p className="mt-1 text-sm text-foreground/60">Get a demo message from the Veil bot.</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex size-9 shrink-0 items-center justify-center rounded-full text-foreground/50 hover:bg-primary/5 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X size={20} />
          </button>
        </div>

        {result ? (
          <div className="mt-6 space-y-4" aria-live="polite">
            <p className="flex items-center gap-2 text-sm font-medium text-emerald-800">
              <CheckCircle size={19} weight="fill" aria-hidden="true" /> You’re ready to try the demo.
            </p>
            <ol className="space-y-3">
              <li className="rounded-card border border-primary/10 p-4">
                <p className="text-sm font-semibold text-primary">1. Tap Join the bot</p>
                <a
                  href={result.join_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-sm bg-primary px-4 text-sm font-medium text-white hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Join the bot
                </a>
              </li>
              <li className="rounded-card border border-primary/10 p-4">
                <p className="text-sm font-semibold text-primary">2. Send ‘hi’ to the bot</p>
              </li>
              <li className="rounded-card border border-primary/10 p-4">
                <p className="text-sm font-semibold text-primary">3. Try a message</p>
                <p className="mt-2 text-sm text-foreground/60">Ask for a checkout link or your recent payments:</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <code className="rounded bg-primary/5 px-3 py-2 font-mono text-sm text-primary">5000 jollof</code>
                  <code className="rounded bg-primary/5 px-3 py-2 font-mono text-sm text-primary">recent</code>
                </div>
              </li>
            </ol>
            <Button variant="secondary" fullWidth onClick={onClose}>Done</Button>
          </div>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={(event) => void submit(event)}>
            <label className="block text-sm font-medium text-foreground" htmlFor="demo-phone">
              Phone number
            </label>
            <div className="flex h-12 overflow-hidden rounded-card border border-primary/15 bg-background focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10">
              <span className="flex shrink-0 items-center border-r border-primary/10 bg-white px-3 font-mono text-sm text-foreground/65">+234</span>
              <input
                id="demo-phone"
                type="tel"
                autoComplete="tel-national"
                inputMode="tel"
                required
                value={phone}
                onChange={(event) => setPhone(event.target.value.replace(/[^\d\s-]/g, ''))}
                placeholder="803 123 4567"
                className="min-w-0 flex-1 bg-transparent px-3 text-base outline-none placeholder:text-foreground/35"
              />
            </div>
            <label className="block text-sm font-medium text-foreground" htmlFor="demo-passcode">
              Demo passcode
            </label>
            <input
              id="demo-passcode"
              type="password"
              autoComplete="off"
              required
              value={passcode}
              onChange={(event) => setPasscode(event.target.value)}
              className="h-12 w-full rounded-card border border-primary/15 bg-background px-3 text-base outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
            {error && <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <Button type="submit" fullWidth size="lg" loading={loading}>
              Get demo link
            </Button>
          </form>
        )}
      </div>
    </dialog>
  )
}
