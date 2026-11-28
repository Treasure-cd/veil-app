import { createContext, useContext } from 'react'
import type { AuthStatus, AuthTab, AuthUser, LoginResponse, SignInStep } from './auth.types'

export interface AuthContextValue {
  status: AuthStatus
  user: AuthUser | null
  step: SignInStep
  error: string | null
  authModalOpen: boolean
  authModalTab: AuthTab
  signIn: () => Promise<void>
  completeWhatsAppSignIn: (res: LoginResponse) => void
  signOut: () => void
  disconnectWallet: () => Promise<void>
  openAuthModal: (tab?: AuthTab) => void
  closeAuthModal: () => void
  clearError: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
