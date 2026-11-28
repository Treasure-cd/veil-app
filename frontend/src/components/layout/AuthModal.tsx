import { useCallback, useEffect, useRef, useState } from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import { WalletReadyState } from '@solana/wallet-adapter-base'
import { CheckCircle, Clock, Copy, Wallet, WhatsappLogo } from '@phosphor-icons/react'
import { useAuth } from '../../auth/useAuth'
import { pollWhatsAppAuth, startWhatsAppAuth } from '../../auth/auth.api'
import type { SignInStep, WhatsAppAuthChallengeResponse } from '../../auth/auth.types'
import { truncateAddress } from '../../lib/format'
import { Button } from '../../components/ui/Button'
import { ConnectWalletButton } from '../../auth/ConnectWalletButton'
import { NETWORK_LABEL, NETWORK } from '../../lib/network'
import { ApiError } from '../../services/api'

type AuthTab = 'wallet' | 'whatsapp'

interface AuthModalProps {
  open: boolean
  dismissible?: boolean
  onClose?: () => void
}

const STEP_LABEL: Record<SignInStep, string> = {
  idle: 'Sign in',
  'requesting-challenge': 'Preparing…',
  'awaiting-signature': 'Confirm in your wallet…',
  verifying: 'Verifying…',
}

const linkClass =
  'font-medium text-primary underline underline-offset-4 hover:text-primary/80 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

function formatCountdown(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0')
  const remainder = (seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${remainder}`
}

export function AuthModal({ open, dismissible = false, onClose }: AuthModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const { wallets, wallet, select, connect, disconnect, connecting, connected, publicKey } =
    useWallet()
  const { signIn, completeWhatsAppSignIn, step, error, clearError } = useAuth()

  const [tab, setTab] = useState<AuthTab>('wallet')
  const [pendingConnect, setPendingConnect] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  // WhatsApp challenge state
  const [waChallenge, setWaChallenge] = useState<WhatsAppAuthChallengeResponse | null>(null)
  const [waLoading, setWaLoading] = useState(false)
  const [waError, setWaError] = useState<string | null>(null)
  const [copiedCommand, setCopiedCommand] = useState(false)
  const [now, setNow] = useState(Date.now())

  // Open / close the native <dialog> (gives us focus trapping and a real backdrop).
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  // Reset transient challenge state when modal closes.
  useEffect(() => {
    if (open) return
    setWaChallenge(null)
    setWaError(null)
    setCopiedCommand(false)
  }, [open])

  // select() only updates state; connect() has to wait until the wallet is actually selected.
  useEffect(() => {
    if (!pendingConnect || !wallet || connected || connecting) return
    setPendingConnect(false)
    connect().catch((e: unknown) => {
      const cancelled = e instanceof Error && /reject|denied|cancel/i.test(e.message)
      setConnectError(
        cancelled ? 'Connection cancelled.' : 'Could not connect to your wallet. Try again.',
      )
    })
  }, [pendingConnect, wallet, connected, connecting, connect])

  const issueWhatsAppChallenge = useCallback(async () => {
    setWaLoading(true)
    setWaError(null)
    setCopiedCommand(false)
    try {
      const res = await startWhatsAppAuth()
      setWaChallenge(res)
      setNow(Date.now())
    } catch (e) {
      setWaError(e instanceof Error ? e.message : 'Could not start WhatsApp sign-in.')
    } finally {
      setWaLoading(false)
    }
  }, [])

  // Start WhatsApp sign-in challenge automatically when switching to WhatsApp tab.
  useEffect(() => {
    if (!open || tab !== 'whatsapp' || waChallenge || waLoading) return
    void issueWhatsAppChallenge()
  }, [open, tab, waChallenge, waLoading, issueWhatsAppChallenge])

  const expiresAt = waChallenge ? Date.parse(waChallenge.expiresAt) : null
  const secondsRemaining =
    expiresAt === null ? 0 : Math.max(0, Math.ceil((expiresAt - now) / 1000))

  // Countdown tick while WhatsApp challenge is active.
  useEffect(() => {
    if (!open || tab !== 'whatsapp' || expiresAt === null) return
    setNow(Date.now())
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [open, tab, expiresAt])

  // Poll backend while waiting for the user to send `login <code>` on WhatsApp.
  useEffect(() => {
    if (!open || tab !== 'whatsapp' || !waChallenge || expiresAt === null || Date.now() >= expiresAt) return
    let cancelled = false
    const challengeToken = waChallenge.challengeToken

    const checkStatus = async () => {
      try {
        const res = await pollWhatsAppAuth(challengeToken)
        if (cancelled) return
        if (res.status === 'verified') {
          setWaChallenge(null)
          completeWhatsAppSignIn({ token: res.token, user: res.user })
        }
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
          setWaError(e.message)
        }
      }
    }

    const interval = window.setInterval(() => {
      if (Date.now() >= expiresAt) {
        window.clearInterval(interval)
        return
      }
      void checkStatus()
    }, 2500)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [open, tab, waChallenge, expiresAt, completeWhatsAppSignIn])

  const installed = wallets.filter((w) => w.readyState === WalletReadyState.Installed)
  const address = publicKey?.toBase58() ?? null
  const busy = step !== 'idle'
  const message = tab === 'wallet' ? error ?? connectError : waError

  function pickWallet(name: (typeof wallets)[number]['adapter']['name']) {
    setConnectError(null)
    clearError()
    select(name)
    setPendingConnect(true)
  }

  function switchTab(next: AuthTab) {
    setTab(next)
    setConnectError(null)
    setWaError(null)
    clearError()
  }

  async function copyLoginCommand(code: string) {
    try {
      await navigator.clipboard.writeText(`login ${code}`)
      setCopiedCommand(true)
      window.setTimeout(() => setCopiedCommand(false), 1800)
    } catch {
      // Clipboard may be unavailable.
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="auth-title"
      // Esc: never closes it by itself. The parent decides through `open`.
      onCancel={(e) => {
        e.preventDefault()
        if (dismissible) onClose?.()
      }}
      // Some browsers close a dialog on a second Esc even when cancelled; put it back.
      onClose={() => {
        if (!open) return
        if (dismissible) onClose?.()
        else dialogRef.current?.showModal()
      }}
      onClick={(e) => {
        if (dismissible && e.target === e.currentTarget) onClose?.()
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-panel border border-primary/10 bg-surface p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm dark:backdrop:bg-black/65"
    >
      <div className="flex flex-col gap-5 p-6 sm:p-8">
        <div className="flex flex-col gap-1.5">
          <h2 id="auth-title" className="text-2xl font-semibold tracking-tight">
            Sign in to Veil
          </h2>
          <p className="text-sm text-foreground/70">
            Connect a Solana wallet or continue with WhatsApp.
          </p>
        </div>

        {/* Tab switcher */}
        <div
          className="inline-flex w-full rounded-pill border border-primary/10 bg-background p-1"
          role="tablist"
          aria-label="Sign in method"
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'wallet'}
            onClick={() => switchTab('wallet')}
            className={`flex min-h-10 flex-1 items-center justify-center gap-2 rounded-pill text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              tab === 'wallet' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            <Wallet size={16} weight="bold" />
            Wallet
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'whatsapp'}
            onClick={() => switchTab('whatsapp')}
            className={`flex min-h-10 flex-1 items-center justify-center gap-2 rounded-pill text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              tab === 'whatsapp' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            <WhatsappLogo size={16} weight="fill" />
            WhatsApp
          </button>
        </div>

        {message && (
          <p role="alert" className="rounded-card bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">
            {message}
          </p>
        )}

        {/* ---- Wallet tab ---- */}
        {tab === 'wallet' && (
          <>
            <p className="text-sm text-foreground/70">
              {address
                ? "Wallet connected. Sign a message to confirm it\u2019s yours. It\u2019s free and doesn\u2019t move any funds."
                : `Connect your Solana wallet to access Veil. Set the wallet network to ${NETWORK_LABEL[NETWORK]} while using the ${NETWORK_LABEL[NETWORK]} app.`}
            </p>

            {address ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between rounded-card border border-primary/10 bg-background px-4 py-3 text-sm">
                  <span className="text-foreground/70">{wallet?.adapter.name ?? 'Wallet'}</span>
                  <span className="font-mono" title={address}>
                    {truncateAddress(address)}
                  </span>
                </div>
                <Button size="lg" fullWidth loading={busy} onClick={() => void signIn()}>
                  {STEP_LABEL[step]}
                </Button>
                <Button variant="secondary" fullWidth disabled={busy} onClick={() => void disconnect()}>
                  Use a different wallet
                </Button>
              </div>
            ) : installed.length === 0 ? (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-foreground/70">
                  No Solana wallet found in this browser. Install{' '}
                  <a className={linkClass} href="https://phantom.com/download" target="_blank" rel="noreferrer">
                    Phantom
                  </a>{' '}
                  or{' '}
                  <a className={linkClass} href="https://www.solflare.com/download/" target="_blank" rel="noreferrer">
                    Solflare
                  </a>
                  , or continue without a wallet using WhatsApp.
                </p>
                <Button
                  size="lg"
                  fullWidth
                  leftIcon={<WhatsappLogo size={18} weight="fill" />}
                  onClick={() => switchTab('whatsapp')}
                >
                  Continue with WhatsApp
                </Button>
              </div>
            ) : installed.length === 1 ? (
              <div className="flex flex-col gap-3">
                <ConnectWalletButton
                  size="lg"
                  fullWidth
                  loading={connecting || pendingConnect}
                  onClick={() => pickWallet(installed[0].adapter.name)}
                />
                <button
                  type="button"
                  onClick={() => switchTab('whatsapp')}
                  className="text-center text-sm font-medium text-foreground/65 underline underline-offset-4 hover:text-primary"
                >
                  Don’t have a crypto wallet? Continue with WhatsApp
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <ul className="flex flex-col gap-2">
                  {installed.map(({ adapter }) => (
                    <li key={adapter.name}>
                      <button
                        type="button"
                        disabled={connecting || pendingConnect}
                        onClick={() => pickWallet(adapter.name)}
                        className="flex w-full items-center gap-3 rounded-card border border-primary/15 px-4 py-3 text-left font-medium transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
                      >
                        <img src={adapter.icon} alt="" className="size-6 rounded-md" />
                        {adapter.name}
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => switchTab('whatsapp')}
                  className="text-center text-sm font-medium text-foreground/65 underline underline-offset-4 hover:text-primary"
                >
                  Don’t have a crypto wallet? Continue with WhatsApp
                </button>
              </div>
            )}
          </>
        )}

        {/* ---- WhatsApp tab ---- */}
        {tab === 'whatsapp' && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-foreground/70">
              Link your WhatsApp number to sign in — no wallet needed. Buyers can still pay with crypto or bank transfer, and funds settle in NGN to your bank account.
            </p>

            {waLoading && !waChallenge ? (
              <div className="rounded-card border border-primary/10 bg-background p-4 text-center text-sm text-foreground/60">
                Preparing your WhatsApp verification code…
              </div>
            ) : waChallenge ? (
              <div className="flex flex-col gap-4">
                <div className="rounded-card border border-primary/10 bg-background p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-foreground/55">
                      Verification code
                    </p>
                    {secondsRemaining > 0 && (
                      <span className="inline-flex items-center gap-1.5 text-xs tabular-nums text-foreground/55">
                        <Clock size={14} aria-hidden="true" /> Expires in {formatCountdown(secondsRemaining)}
                      </span>
                    )}
                  </div>

                  {secondsRemaining > 0 ? (
                    <>
                      <p className="my-3 break-all text-center font-mono text-3xl font-semibold tracking-[0.18em] text-primary">
                        {waChallenge.code}
                      </p>
                      <p className="text-center text-xs text-foreground/65">
                        Send <span className="font-mono font-semibold text-primary">login {waChallenge.code}</span> to Veil on WhatsApp.
                      </p>
                    </>
                  ) : (
                    <div className="mt-3 space-y-3 text-center">
                      <p className="text-sm text-red-700 dark:text-red-300">
                        This verification code has expired.
                      </p>
                      <Button size="sm" loading={waLoading} onClick={() => void issueWhatsAppChallenge()}>
                        Generate a new code
                      </Button>
                    </div>
                  )}
                </div>

                {secondsRemaining > 0 && (
                  <div className="flex flex-col gap-2">
                    {waChallenge.sendUrl && (
                      <a
                        href={waChallenge.sendUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-sm bg-[#25D366] px-4 text-sm font-semibold text-[#063b1d] transition-colors hover:bg-[#1ebe5b] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        <WhatsappLogo size={18} weight="fill" aria-hidden="true" />
                        Open WhatsApp to verify
                      </a>
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      fullWidth
                      leftIcon={copiedCommand ? <CheckCircle size={15} weight="fill" /> : <Copy size={15} />}
                      onClick={() => void copyLoginCommand(waChallenge.code)}
                    >
                      {copiedCommand ? 'Copied command' : `Copy "login ${waChallenge.code}"`}
                    </Button>
                    <p className="pt-1 text-center text-xs text-foreground/55" aria-live="polite">
                      Waiting for WhatsApp message… this screen updates automatically.
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <Button loading={waLoading} onClick={() => void issueWhatsAppChallenge()}>
                Try again
              </Button>
            )}
          </div>
        )}
      </div>
    </dialog>
  )
}
