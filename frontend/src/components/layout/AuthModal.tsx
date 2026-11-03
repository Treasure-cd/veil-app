import { useEffect, useRef, useState } from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import { WalletReadyState } from '@solana/wallet-adapter-base'
import { useAuth } from '../../auth/useAuth'
import type { SignInStep } from '../../auth/auth.types'
import { truncateAddress } from '../../lib/format'
import { Button } from '../../components/ui/Button'
import { ConnectWalletButton } from '../../auth/ConnectWalletButton'

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
  'font-medium text-primary underline underline-offset-4 hover:text-secondary ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

export function AuthModal({ open, dismissible = false, onClose }: AuthModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const { wallets, wallet, select, connect, disconnect, connecting, connected, publicKey } =
    useWallet()
  const { signIn, step, error, clearError } = useAuth()

  const [pendingConnect, setPendingConnect] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

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
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-panel bg-white p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm"
    >
      <div className="flex flex-col gap-6 p-6 sm:p-8">
        <div className="flex flex-col gap-2">
          <h2 id="auth-title" className="text-2xl font-semibold tracking-tight">
            Sign in to Veil
          </h2>
          <p className="text-foreground/70">
            {address
              ? 'Wallet connected. Sign a message to confirm it’s yours. It’s free and doesn’t move any funds.'
              : 'Connect your Solana wallet to access your dashboard.'}
          </p>
        </div>

        {message && (
          <p role="alert" className="rounded-card bg-red-50 px-4 py-3 text-sm text-red-700">
            {message}
          </p>
        )}

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
      </div>
    </dialog>
  )
}
