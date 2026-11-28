import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CheckCircle, Wallet, WhatsappLogo, X } from '@phosphor-icons/react'
import { useAuth } from '../../auth/useAuth'
import { truncateAddress } from '../../lib/format'
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
  const { status, user, openAuthModal, disconnectWallet } = useAuth()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DemoLinkResponse | null>(null)
  const [resultWalletAddress, setResultWalletAddress] = useState<string | null>(null)
  const walletLinked =
    status === 'authenticated' &&
    user?.hasWallet !== false &&
    Boolean(user?.address && !user.address.startsWith('whatsapp:'))

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    if (open) return
    setPhone('')
    setError(null)
    setResult(null)
    setResultWalletAddress(null)
  }, [open])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const nationalNumber = phone.replace(/\D/g, '').replace(/^0/, '')
      const response = await api<DemoLinkResponse>('/v1/whatsapp/demo-link', {
        method: 'POST',
        body: JSON.stringify({ phone: `+234${nationalNumber}` }),
      })
      setResultWalletAddress(walletLinked ? user?.address ?? null : null)
      setResult(response)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Your wallet session could not be verified. Reconnect it, or retry without a wallet.')
      } else if (err instanceof ApiError && err.status === 403) {
        setError('Demo access is currently unavailable. Please try again later.')
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
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-panel border border-primary/10 bg-surface p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm max-sm:mb-0 max-sm:mt-auto max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-panel dark:backdrop:bg-black/65"
    >
      <div className="p-5 sm:p-7">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-card bg-primary/10 text-primary">
              <WhatsappLogo size={22} weight="fill" aria-hidden="true" />
            </span>
            <div>
              <h2 id="whatsapp-demo-title" className="text-xl font-semibold text-primary">Try it on WhatsApp</h2>
              <p className="mt-1 text-sm text-foreground/60">
                Try the demo with Veil’s shared wallet, or connect yours so checkout links pay you.
              </p>
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
            <p className="flex items-center gap-2 text-sm font-medium text-emerald-800 dark:text-emerald-300">
              <CheckCircle size={19} weight="fill" aria-hidden="true" /> You’re ready to try the demo.
            </p>
            {resultWalletAddress ? (
              <p className="rounded-card bg-primary/5 px-3 py-2 text-xs text-primary">
                Checkout links from this number pay your wallet{' '}
                <span className="font-mono" title={resultWalletAddress}>{truncateAddress(resultWalletAddress)}</span>.
              </p>
            ) : (
              <p className="rounded-card bg-primary/5 px-3 py-2 text-xs text-primary">
                Without a connected wallet, checkout links from this number pay Veil’s shared demo wallet, not you.
              </p>
            )}
            <ol className="space-y-3">
              <li className="rounded-card border border-primary/10 p-4">
                <p className="text-sm font-semibold text-primary">1. Tap Join the bot</p>
                <a
                  href={result.join_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-sm bg-primary-action px-4 text-sm font-medium text-white hover:bg-primary-action-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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
            <div className="rounded-card border border-primary/10 bg-background/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Wallet size={18} weight="bold" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-primary">
                      {walletLinked ? 'Personal receiving wallet' : 'Wallet optional'}
                    </p>
                    <p
                      className="truncate font-mono text-xs text-foreground/60"
                      title={walletLinked ? user?.address ?? undefined : undefined}
                    >
                      {walletLinked
                        ? truncateAddress(user?.address ?? '')
                        : 'Without one, demo payments go to Veil’s shared demo wallet.'}
                    </p>
                  </div>
                </div>
                {walletLinked && (
                  <button
                    type="button"
                    onClick={() => void disconnectWallet()}
                    className="shrink-0 text-xs font-medium text-primary underline underline-offset-2 hover:text-primary/80 focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    Change
                  </button>
                )}
              </div>
              {!walletLinked && (
                <Button type="button" className="mt-3" fullWidth onClick={openAuthModal}>
                  Connect wallet (optional)
                </Button>
              )}
            </div>

            <label className="block text-sm font-medium text-foreground" htmlFor="demo-phone">
              Phone number
            </label>
            <div className="flex h-12 overflow-hidden rounded-card border border-primary/15 bg-background focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10">
              <span className="flex shrink-0 items-center border-r border-primary/10 bg-surface px-3 font-mono text-sm text-foreground/65">+234</span>
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
            {error && <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">{error}</p>}
            <Button type="submit" fullWidth size="lg" loading={loading}>
              Get demo link
            </Button>
          </form>
        )}
      </div>
    </dialog>
  )
}
