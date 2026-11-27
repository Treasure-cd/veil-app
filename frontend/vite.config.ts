import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  // Vite serves a static browser bundle, so expose only the client settings
  // the app needs as explicit process.env replacements at build time.
  const fileEnv = loadEnv(mode, process.cwd(), '')
  const readVar = (key: string, ...aliases: string[]) => {
    for (const name of [...aliases, key, `VITE_${key}`]) {
      const value = process.env[name] ?? fileEnv[name]
      if (value !== undefined) return value
    }
    return undefined
  }

  const rawNetwork = readVar('SOLANA_NETWORK', 'VITE_SOLANA_NETWORK')?.trim().toLowerCase()
  if (rawNetwork && !['mainnet-beta', 'mainnet', 'devnet'].includes(rawNetwork)) {
    throw new Error("SOLANA_NETWORK must be set to 'mainnet-beta', 'mainnet', or 'devnet'.")
  }
  const network = rawNetwork === 'devnet' ? 'devnet' : 'mainnet-beta'
  const rpcUrl =
    readVar('SOLANA_RPC_URL', 'VITE_SOLANA_RPC_URL')?.trim() ||
    (network === 'devnet' ? 'https://api.devnet.solana.com' : 'https://api.mainnet-beta.solana.com')
  const wsUrl =
    readVar('SOLANA_WS_URL', 'VITE_SOLANA_WS_URL')?.trim() ||
    rpcUrl.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  const usdcMint =
    readVar('SOLANA_USDC_MINT', 'VITE_SOLANA_USDC_MINT', 'VITE_USDC_MINT', 'USDC_MINT')?.trim() ||
    (network === 'devnet'
      ? '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU'
      : 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')
  const apiUrl = readVar('API_URL', 'VITE_API_URL')?.trim() ?? ''

  if (command === 'build' && mode === 'production') {
    if (!rawNetwork || !['mainnet', 'mainnet-beta'].includes(rawNetwork)) {
      throw new Error('Production builds require SOLANA_NETWORK=mainnet-beta.')
    }
    for (const [name, value] of [
      ['API_URL', apiUrl],
      ['SOLANA_RPC_URL', rpcUrl],
      ['SOLANA_WS_URL', wsUrl],
    ] as const) {
      let parsed: URL
      try {
        parsed = new URL(value)
      } catch {
        throw new Error(`Production builds require a valid ${name}.`)
      }
      const protocol = name === 'SOLANA_WS_URL' ? 'wss:' : 'https:'
      if (parsed.protocol !== protocol) {
        throw new Error(`Production ${name} must use ${protocol.toUpperCase()}.`)
      }
      if (
        (name === 'SOLANA_RPC_URL' || name === 'SOLANA_WS_URL') &&
        (
          ['api.devnet.solana.com', 'api.mainnet-beta.solana.com'].includes(parsed.hostname) ||
          parsed.hostname.endsWith('.example') ||
          parsed.hostname.includes('your-mainnet-rpc-provider')
        )
      ) {
        throw new Error(`Production ${name} must use a dedicated Mainnet RPC provider.`)
      }
    }
  }

  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.API_URL': JSON.stringify(apiUrl),
      'process.env.SOLANA_NETWORK': JSON.stringify(network),
      'process.env.SOLANA_RPC_URL': JSON.stringify(rpcUrl),
      'process.env.SOLANA_WS_URL': JSON.stringify(wsUrl),
      'process.env.SOLANA_USDC_MINT': JSON.stringify(usdcMint),
    },
  }
})
