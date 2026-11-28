import { Plus, SignOut, EnvelopeSimple } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import Logo from '../Logo'
import { IS_MAINNET, NETWORK_LABEL, USDC_MINT } from '../../lib/network'
import { ConnectWalletButton } from '../../auth/ConnectWalletButton'
import { Button } from '../../components/ui/Button'
import { useNavigate } from 'react-router'
import { MoneyDisplayToggle } from '../ui/MoneyDisplayToggle'
import { ThemeToggle } from '../ui/ThemeToggle'

function NetworkBadge() {
  const cluster = IS_MAINNET ? 'mainnet-beta' : 'devnet'
  return (
    <span
      title={`Solana ${NETWORK_LABEL[cluster]} · USDC mint ${USDC_MINT}`}
      aria-label={`Solana ${NETWORK_LABEL[cluster]}`}
      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-pill border border-primary/10 bg-surface px-2 text-sm font-medium sm:h-9 sm:px-2.5 lg:gap-2 lg:px-3"
    >
      <span
        className={`size-2 rounded-full ${IS_MAINNET ? 'bg-emerald-500' : 'bg-amber-500'}`}
        aria-hidden="true"
      />
      <span className="hidden lg:inline">{NETWORK_LABEL[cluster]}</span>
    </span>
  )
}

/** Returns true if the user logged in via email (placeholder address). */
function isEmailUser(address?: string | null): boolean {
  return Boolean(address?.startsWith('email:'))
}

export function Header() {
  const { user, disconnectWallet, signOut } = useAuth()
  const navigate = useNavigate()
  const [walletMenuOpen, setWalletMenuOpen] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const walletMenuRef = useRef<HTMLDivElement>(null)

  const emailMode = isEmailUser(user?.address)

  useEffect(() => {
    if (!walletMenuOpen) return
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!walletMenuRef.current?.contains(event.target as Node)) setWalletMenuOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setWalletMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [walletMenuOpen])

  async function handleDisconnect() {
    setDisconnecting(true)
    setWalletMenuOpen(false)
    try {
      if (emailMode) {
        signOut()
      } else {
        await disconnectWallet()
      }
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-1 border-b border-primary/5 bg-background/80 px-2.5 backdrop-blur-md sm:gap-2 sm:px-4 md:gap-3 md:px-8 lg:px-10">
      {/* The sidebar carries the logo on desktop; on mobile it lives here. */}
      <Logo className="h-4 shrink-0 sm:h-5 md:hidden" />

      <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-2 md:gap-3">
        <ThemeToggle />
        <MoneyDisplayToggle />
        {!emailMode && <NetworkBadge />}
        <Button
          size="sm"
          className="hidden sm:inline-flex"
          aria-label="New request"
          leftIcon={<Plus size={16} weight="bold" />}
          onClick={() => navigate('/payments')}
        >
          <span className="hidden lg:inline">New request</span>
        </Button>
        {/* User profile anchor */}
        <div className="relative" ref={walletMenuRef}>
          {emailMode ? (
            <Button
              variant="secondary"
              size="sm"
              className="max-sm:h-8 max-sm:px-2.5 max-sm:text-xs"
              aria-haspopup="menu"
              aria-expanded={walletMenuOpen}
              onClick={() => setWalletMenuOpen((open) => !open)}
              leftIcon={<EnvelopeSimple size={16} weight="bold" className="hidden sm:inline" />}
            >
              <span className="max-w-[12ch] truncate">{user?.email ?? 'Account'}</span>
            </Button>
          ) : (
            <ConnectWalletButton
              size="sm"
              address={user?.address}
              aria-haspopup={user ? 'menu' : undefined}
              aria-expanded={user ? walletMenuOpen : undefined}
              onClick={user ? () => setWalletMenuOpen((open) => !open) : undefined}
            />
          )}
          {user && walletMenuOpen && (
            <div
              role="menu"
              aria-label="Account options"
              className="absolute right-0 top-[calc(100%+0.65rem)] z-30 w-[min(18rem,calc(100vw-2rem))] overflow-hidden rounded-card border border-primary/10 bg-surface p-2 shadow-veil-lg"
            >
              <div className="px-3 py-2.5">
                <p className="text-xs font-medium uppercase tracking-wide text-foreground/50">
                  {emailMode ? 'Email account' : 'Connected wallet'}
                </p>
                <p className="mt-1 truncate font-mono text-sm text-foreground" title={emailMode ? user.email ?? '' : user.address}>
                  {emailMode ? user.email : user.address}
                </p>
              </div>
              <div className="my-1 h-px bg-primary/10" />
              <button
                type="button"
                role="menuitem"
                disabled={disconnecting}
                onClick={() => void handleDisconnect()}
                className="flex min-h-11 w-full items-center gap-2.5 rounded-card px-3 text-left text-sm font-medium text-red-700 transition-colors hover:bg-red-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60 dark:text-red-400 dark:hover:bg-red-950/40"
              >
                <SignOut size={18} weight="bold" aria-hidden="true" />
                {disconnecting ? 'Signing out…' : emailMode ? 'Sign out' : 'Disconnect'}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
