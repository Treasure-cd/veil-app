import type { ReactNode } from 'react'
import { AuthProvider } from '../auth/AuthProvider'
import { SolanaProvider } from './SolanaProvider.tsx'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <SolanaProvider>
      <AuthProvider>{children}</AuthProvider>
    </SolanaProvider>
  )
}
