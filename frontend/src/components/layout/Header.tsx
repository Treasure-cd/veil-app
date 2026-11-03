import { Plus } from '@phosphor-icons/react'
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
  const { user } = useAuth()
  const navigate = useNavigate()

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
        <ConnectWalletButton size="sm" address={user?.address} />
      </div>
    </header>
  )
}
