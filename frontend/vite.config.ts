import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  // Vite serves a static browser bundle, so expose only the client settings
  // the app needs as explicit process.env replacements at build time.
  const fileEnv = loadEnv(mode, process.cwd(), '')
  const env = {
    ...fileEnv,
    API_URL: process.env.API_URL ?? fileEnv.API_URL,
    SOLANA_NETWORK: process.env.SOLANA_NETWORK ?? fileEnv.SOLANA_NETWORK,
    SOLANA_RPC_URL: process.env.SOLANA_RPC_URL ?? fileEnv.SOLANA_RPC_URL,
    SOLANA_WS_URL: process.env.SOLANA_WS_URL ?? fileEnv.SOLANA_WS_URL,
    SOLANA_USDC_MINT: process.env.SOLANA_USDC_MINT ?? fileEnv.SOLANA_USDC_MINT,
    USDC_MINT: process.env.USDC_MINT ?? fileEnv.USDC_MINT,
  }
  const network = env.SOLANA_NETWORK?.trim().toLowerCase()

  if (command === 'build' && mode === 'production') {
    if (!['devnet', 'mainnet', 'mainnet-beta'].includes(network ?? '')) {
      throw new Error('Production builds require SOLANA_NETWORK to be explicitly set to devnet or mainnet-beta.')
    }

    for (const [name, value] of [
      ['API_URL', env.API_URL],
      ['SOLANA_RPC_URL', env.SOLANA_RPC_URL],
    ] as const) {
      let parsed: URL
      try {
        parsed = new URL(value ?? '')
      } catch {
        throw new Error(`Production builds require a valid ${name}.`)
      }
      if (parsed.protocol !== 'https:') {
        throw new Error(`Production ${name} must use HTTPS.`)
      }
    }
  }

  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.API_URL': JSON.stringify(env.API_URL ?? ''),
      'process.env.SOLANA_NETWORK': JSON.stringify(env.SOLANA_NETWORK ?? ''),
      'process.env.SOLANA_RPC_URL': JSON.stringify(env.SOLANA_RPC_URL ?? ''),
      'process.env.SOLANA_WS_URL': JSON.stringify(env.SOLANA_WS_URL ?? ''),
      'process.env.SOLANA_USDC_MINT': JSON.stringify(env.SOLANA_USDC_MINT ?? env.USDC_MINT ?? ''),
    },
  }
})
