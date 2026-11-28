export type Network = 'mainnet-beta' | 'devnet'

const configuredNetwork = process.env.SOLANA_NETWORK?.trim().toLowerCase()

if (configuredNetwork && !['mainnet-beta', 'mainnet', 'devnet'].includes(configuredNetwork)) {
  throw new Error('SOLANA_NETWORK must be set to mainnet-beta, mainnet, or devnet.')
}

export const NETWORK: Network = configuredNetwork === 'devnet' ? 'devnet' : 'mainnet-beta'
export const IS_MAINNET = NETWORK === 'mainnet-beta'
export const IS_DEVNET = NETWORK === 'devnet'

export const SOL_MINT = 'So11111111111111111111111111111111111111112'
export const MAINNET_USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
export const DEVNET_USDC_MINT = '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU'
export const USDT_MINT = process.env.SOLANA_USDT_MINT || ''

const USDC_MINTS: Record<Network, string> = {
  devnet: DEVNET_USDC_MINT,
  'mainnet-beta': MAINNET_USDC_MINT,
}

const DEFAULT_RPC_URLS: Record<Network, string> = {
  devnet: 'https://api.devnet.solana.com',
  'mainnet-beta': 'https://api.mainnet-beta.solana.com',
}

export const USDC_MINT = process.env.SOLANA_USDC_MINT || USDC_MINTS[NETWORK]
export const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL || DEFAULT_RPC_URLS[NETWORK]
export const SOLANA_WS_URL =
  process.env.SOLANA_WS_URL ||
  SOLANA_RPC_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')

export const SOLANA_GENESIS_HASH: Record<Network, string> = {
  devnet: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  'mainnet-beta': '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
}

export const NETWORK_LABEL: Record<Network, string> = {
  'mainnet-beta': 'Mainnet',
  devnet: 'Devnet',
}

export const KNOWN_TOKENS: Record<string, { symbol: string; decimals: number; network?: Network }> = {
  [MAINNET_USDC_MINT]: { symbol: 'USDC', decimals: 6, network: 'mainnet-beta' },
  [DEVNET_USDC_MINT]: { symbol: 'USDC', decimals: 6, network: 'devnet' },
  [USDC_MINT]: { symbol: 'USDC', decimals: 6, network: NETWORK },
  ...(USDT_MINT ? { [USDT_MINT]: { symbol: 'USDT', decimals: 6, network: NETWORK } } : {}),
  [SOL_MINT]: { symbol: 'SOL', decimals: 9 },
}

export function solanaExplorerTxUrl(signature: string): string {
  const cluster = IS_DEVNET ? '?cluster=devnet' : ''
  return `https://explorer.solana.com/tx/${encodeURIComponent(signature)}${cluster}`
}
