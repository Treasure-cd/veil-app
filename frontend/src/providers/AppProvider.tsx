import { Outlet } from 'react-router'
import { AuthProvider } from '../auth/AuthProvider'
import { SolanaProvider } from './SolanaProvider.tsx'

export function AppProviders() {
  return (
    <SolanaProvider>
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    </SolanaProvider>
  )
}
