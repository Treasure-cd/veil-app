import { Plus, SignOut } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import { NETWORK, NETWORK_LABEL } from '../../lib/network'
import { ConnectWalletButton } from '../../auth/ConnectWalletButton'
import { Button } from '../../components/ui/Button'
import { useNavigate } from 'react-router'

function NetworkBadge() {
  const live = NETWORK === 'mainnet-beta'
  return (
    <span className="inline-flex h-9 items-center gap-2 rounded-pill border border-primary/10 bg-white px-3 text-sm font-medium">
      <span
        className={`size-2 rounded-full ${live ? 'bg-emerald-500' : 'bg-amber-500'}`}
        aria-hidden="true"
      />
      <span className="sr-only sm:not-sr-only">{NETWORK_LABEL[NETWORK]}</span>
    </span>
  )
}

export function Header() {
  const { user, disconnectWallet } = useAuth()
  const navigate = useNavigate()
  const [walletMenuOpen, setWalletMenuOpen] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const walletMenuRef = useRef<HTMLDivElement>(null)

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
      await disconnectWallet()
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-2 border-b border-primary/5 bg-background/80 px-4 backdrop-blur-md md:gap-3 md:px-8">
      {/* The sidebar carries the logo on desktop; on mobile it lives here. */}
      <span className="text-xl font-semibold tracking-tight text-primary md:hidden">Veil</span>

      <div className="ml-auto flex items-center gap-2 md:gap-3">
        <NetworkBadge />
        <Button
          size="sm"
          aria-label="New request"
          leftIcon={<Plus size={16} weight="bold" />}
          onClick={() => navigate('/payments')}
        >
          <span className="hidden sm:inline">New request</span>
        </Button>
        {/* Wallet stays on the far right as the user profile anchor */}
        <div className="relative" ref={walletMenuRef}>
          <ConnectWalletButton
            size="sm"
            address={user?.address}
            aria-haspopup={user ? 'menu' : undefined}
            aria-expanded={user ? walletMenuOpen : undefined}
            onClick={user ? () => setWalletMenuOpen((open) => !open) : undefined}
          />
          {user && walletMenuOpen && (
            <div
              role="menu"
              aria-label="Wallet options"
              className="absolute right-0 top-[calc(100%+0.65rem)] z-30 w-[min(18rem,calc(100vw-2rem))] overflow-hidden rounded-card border border-primary/10 bg-white p-2 shadow-veil-lg"
            >
              <div className="px-3 py-2.5">
                <p className="text-xs font-medium uppercase tracking-wide text-foreground/50">Connected wallet</p>
                <p className="mt-1 truncate font-mono text-sm text-foreground" title={user.address}>
                  {user.address}
                </p>
              </div>
              <div className="my-1 h-px bg-primary/10" />
              <button
                type="button"
                role="menuitem"
                disabled={disconnecting}
                onClick={() => void handleDisconnect()}
                className="flex min-h-11 w-full items-center gap-2.5 rounded-card px-3 text-left text-sm font-medium text-red-700 transition-colors hover:bg-red-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
              >
                <SignOut size={18} weight="bold" aria-hidden="true" />
                {disconnecting ? 'Disconnecting…' : 'Disconnect'}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
