export type Network = 'mainnet-beta' | 'devnet'

export const NETWORK: Network =
  import.meta.env.VITE_SOLANA_NETWORK === 'mainnet-beta' ? 'mainnet-beta' : 'devnet'

export const NETWORK_LABEL: Record<Network, string> = {
  'mainnet-beta': 'Mainnet',
  devnet: 'Devnet',
}
