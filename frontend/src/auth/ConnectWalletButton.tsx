import { Wallet } from '@phosphor-icons/react'
import { truncateAddress } from '../lib/format'
import { Button, type ButtonProps } from '../components/ui/Button'

interface ConnectWalletButtonProps
  extends Omit<ButtonProps, 'variant' | 'leftIcon' | 'children'> {
  address?: string | null
}

// UI only. Pass `address` to show the connected state, `loading` while connecting.
export function ConnectWalletButton({ address, loading, ...rest }: ConnectWalletButtonProps) {
  if (address) {
    return (
      <Button
        variant="secondary"
        title={address}
        leftIcon={<Wallet size={18} weight="bold" />}
        {...rest}
      >
        <span className="font-mono">{truncateAddress(address)}</span>
      </Button>
    )
  }

  return (
    <Button loading={loading} leftIcon={<Wallet size={20} weight="bold" />} {...rest}>
      {loading ? 'Connecting…' : 'Connect wallet'}
    </Button>
  )
}
