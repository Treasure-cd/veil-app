export type Network = 'mainnet-beta' | 'devnet'

export const NETWORK: Network =
  import.meta.env.VITE_SOLANA_NETWORK === 'mainnet-beta' ? 'mainnet-beta' : 'devnet'

const USDC_MINTS: Record<Network, string> = {
  devnet: '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU',
  'mainnet-beta': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
}

export const USDC_MINT = USDC_MINTS[NETWORK]

export const SOLANA_GENESIS_HASH: Record<Network, string> = {
  devnet: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  'mainnet-beta': '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
}

export const NETWORK_LABEL: Record<Network, string> = {
  'mainnet-beta': 'Mainnet',
  devnet: 'Devnet',
}
