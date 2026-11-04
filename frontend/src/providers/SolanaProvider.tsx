import type { ReactNode } from 'react'
import type { Adapter } from '@solana/wallet-adapter-base'
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react'
import { clusterApiUrl } from '@solana/web3.js'

const ENDPOINT =
  (import.meta.env.VITE_SOLANA_RPC_URL as string | undefined) ?? clusterApiUrl('devnet')

const WALLETS: Adapter[] = []

export function SolanaProvider({ children }: { children: ReactNode }) {
  return (
    <ConnectionProvider endpoint={ENDPOINT}>
      <WalletProvider wallets={WALLETS} autoConnect={false}>
        {children}
      </WalletProvider>
    </ConnectionProvider>
  )
}
