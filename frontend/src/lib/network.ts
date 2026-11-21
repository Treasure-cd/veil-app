export type Network = 'mainnet-beta' | 'devnet'

const configuredNetwork = process.env.SOLANA_NETWORK?.toLowerCase()
export const NETWORK: Network = configuredNetwork === 'mainnet-beta' || configuredNetwork === 'mainnet'
  ? 'mainnet-beta'
  : 'devnet'

const USDC_MINTS: Record<Network, string> = {
  devnet: '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU',
  'mainnet-beta': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
}

export const USDC_MINT =
  process.env.SOLANA_USDC_MINT ||
  USDC_MINTS[NETWORK]

export const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL || undefined

export const SOLANA_GENESIS_HASH: Record<Network, string> = {
  devnet: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  'mainnet-beta': '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
}

export const NETWORK_LABEL: Record<Network, string> = {
  'mainnet-beta': 'Mainnet',
  devnet: 'Devnet',
}
