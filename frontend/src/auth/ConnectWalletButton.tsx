import { Wallet } from '@phosphor-icons/react'
import { truncateAddress } from '../lib/format'
import { Button, type ButtonProps } from '../components/ui/Button'

interface ConnectWalletButtonProps
  extends Omit<ButtonProps, 'variant' | 'leftIcon' | 'children'> {
  address?: string | null
}

// UI only. Pass `address` to show the connected state, `loading` while connecting.
export function ConnectWalletButton({ address, loading, className = '', ...rest }: ConnectWalletButtonProps) {
  if (address) {
    return (
      <Button
        variant="secondary"
        title={address}
        className={`max-sm:h-8 max-sm:px-2.5 max-sm:text-xs ${className}`}
        leftIcon={<Wallet size={16} weight="bold" className="hidden sm:inline" />}
        {...rest}
      >
        <span className="font-mono">{truncateAddress(address)}</span>
      </Button>
    )
  }

  return (
    <Button loading={loading} className={className} leftIcon={<Wallet size={20} weight="bold" />} {...rest}>
      {loading ? 'Connecting…' : 'Connect wallet'}
    </Button>
  )
}
