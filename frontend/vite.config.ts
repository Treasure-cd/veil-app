import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Vite serves a static browser bundle, so expose only the client settings
  // the app needs as explicit process.env replacements at build time.
  const env = loadEnv(mode, process.cwd(), '')

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
