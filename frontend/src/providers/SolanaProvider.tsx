import type { ReactNode } from 'react'
import { useLocation } from 'react-router' // or 'react-router-dom' depending on your setup
import type { Adapter } from '@solana/wallet-adapter-base'
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react'
import { clusterApiUrl } from '@solana/web3.js'

const ENDPOINT =
  (import.meta.env.VITE_SOLANA_RPC_URL as string | undefined) ?? clusterApiUrl('devnet')

const WALLETS: Adapter[] = []

export function SolanaProvider({ children }: { children: ReactNode }) {
  const location = useLocation()

  // Check if we are on the landing page ("/") or checkout page ("/pay/...")
  const isLandingPage = location.pathname === '/'
  const isCheckoutPage = location.pathname.startsWith('/pay/')

  // Only auto-connect if we are NOT on the landing or checkout pages
  const shouldAutoConnect = !isLandingPage && !isCheckoutPage

  return (
    <ConnectionProvider endpoint={ENDPOINT}>
      <WalletProvider wallets={WALLETS} autoConnect={shouldAutoConnect}>
        {children}
      </WalletProvider>
    </ConnectionProvider>
  )
}
