import type { ReactNode } from 'react'
import type { Adapter } from '@solana/wallet-adapter-base'
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react'
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui'
import { clusterApiUrl } from '@solana/web3.js'
import { NETWORK, SOLANA_RPC_URL } from '../lib/network'

const ENDPOINT =
  SOLANA_RPC_URL || clusterApiUrl(NETWORK)
const WS_ENDPOINT =
  process.env.SOLANA_WS_URL ||
  ENDPOINT.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')

const WALLETS: Adapter[] = []

export function SolanaProvider({ children }: { children: ReactNode }) {
  return (
    <ConnectionProvider endpoint={ENDPOINT} config={{ wsEndpoint: WS_ENDPOINT }}>
      <WalletProvider wallets={WALLETS} autoConnect={true}>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  )
}
