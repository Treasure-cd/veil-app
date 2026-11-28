import { useEffect, useRef, useState } from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import { WalletReadyState } from '@solana/wallet-adapter-base'
import { useAuth } from '../../auth/useAuth'
import type { SignInStep } from '../../auth/auth.types'
import { truncateAddress } from '../../lib/format'
import { Button } from '../../components/ui/Button'
import { ConnectWalletButton } from '../../auth/ConnectWalletButton'
import { NETWORK_LABEL, NETWORK } from '../../lib/network'
import { EnvelopeSimple, Wallet } from '@phosphor-icons/react'

type AuthTab = 'wallet' | 'email'

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

export function AuthModal({ open, dismissible = false, onClose }: AuthModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const { wallets, wallet, select, connect, disconnect, connecting, connected, publicKey } =
    useWallet()
  const { signIn, signInWithEmail, step, error, clearError } = useAuth()

  const [tab, setTab] = useState<AuthTab>('wallet')
  const [pendingConnect, setPendingConnect] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  // Email form state
  const [emailMode, setEmailMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // Open / close the native <dialog> (gives us focus trapping and a real backdrop).
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
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

  const installed = wallets.filter((w) => w.readyState === WalletReadyState.Installed)
  const address = publicKey?.toBase58() ?? null
  const busy = step !== 'idle'
  const message = error ?? connectError

  function pickWallet(name: (typeof wallets)[number]['adapter']['name']) {
    setConnectError(null)
    clearError()
    select(name)
    setPendingConnect(true)
  }

  function switchTab(next: AuthTab) {
    setTab(next)
    setConnectError(null)
    clearError()
  }

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) return
    await signInWithEmail(email.trim(), password, emailMode === 'register')
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
      <div className="flex flex-col gap-6 p-6 sm:p-8">
        <div className="flex flex-col gap-2">
          <h2 id="auth-title" className="text-2xl font-semibold tracking-tight">
            Sign in to Veil
          </h2>
          <p className="text-sm text-foreground/70">
            Choose how you'd like to access the platform.
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
            aria-selected={tab === 'email'}
            onClick={() => switchTab('email')}
            className={`flex min-h-10 flex-1 items-center justify-center gap-2 rounded-pill text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              tab === 'email' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            <EnvelopeSimple size={16} weight="bold" />
            Email
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
              <p className="text-sm text-foreground/70">
                No Solana wallet found in this browser. Install{' '}
                <a className={linkClass} href="https://phantom.com/download" target="_blank" rel="noreferrer">
                  Phantom
                </a>{' '}
                or{' '}
                <a className={linkClass} href="https://www.solflare.com/download/" target="_blank" rel="noreferrer">
                  Solflare
                </a>
                , then reload this page.
              </p>
            ) : installed.length === 1 ? (
              <ConnectWalletButton
                size="lg"
                fullWidth
                loading={connecting || pendingConnect}
                onClick={() => pickWallet(installed[0].adapter.name)}
              />
            ) : (
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
            )}
          </>
        )}

        {/* ---- Email tab ---- */}
        {tab === 'email' && (
          <form onSubmit={(e) => void handleEmailSubmit(e)} className="flex flex-col gap-4">
            <p className="text-sm text-foreground/70">
              {emailMode === 'register'
                ? 'Create an account with your email. You can connect a wallet later.'
                : 'Sign in with your email and password.'}
            </p>
            <div className="space-y-1.5">
              <label htmlFor="auth-email" className="text-sm font-medium">
                Email
              </label>
              <input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="auth-password" className="text-sm font-medium">
                Password
              </label>
              <input
                id="auth-password"
                type="password"
                required
                minLength={8}
                autoComplete={emailMode === 'register' ? 'new-password' : 'current-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={emailMode === 'register' ? 'At least 8 characters' : '••••••••'}
                className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>
            <Button type="submit" size="lg" fullWidth loading={busy}>
              {busy ? 'Verifying…' : emailMode === 'register' ? 'Create account' : 'Sign in'}
            </Button>
            <p className="text-center text-sm text-foreground/60">
              {emailMode === 'login' ? (
                <>
                  Don't have an account?{' '}
                  <button
                    type="button"
                    onClick={() => { setEmailMode('register'); clearError() }}
                    className={linkClass}
                  >
                    Sign up
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{' '}
                  <button
                    type="button"
                    onClick={() => { setEmailMode('login'); clearError() }}
                    className={linkClass}
                  >
                    Sign in
                  </button>
                </>
              )}
            </p>
          </form>
        )}
      </div>
    </dialog>
  )
}
