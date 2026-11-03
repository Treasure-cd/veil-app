import type { ReactNode } from 'react'
import type { Adapter } from '@solana/wallet-adapter-base'
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react'
import { clusterApiUrl } from '@solana/web3.js'

const ENDPOINT =
  (import.meta.env.VITE_SOLANA_RPC_URL as string | undefined) ?? clusterApiUrl('devnet')

// Phantom, Solflare and others register themselves through the Wallet Standard,
// so no adapter list is needed. Keep this constant outside the component so it stays referentially stable.
const WALLETS: Adapter[] = []

export function SolanaProvider({ children }: { children: ReactNode }) {
  return (
    <ConnectionProvider endpoint={ENDPOINT}>
      <WalletProvider wallets={WALLETS} autoConnect>
        {children}
      </WalletProvider>
    </ConnectionProvider>
  )
}
