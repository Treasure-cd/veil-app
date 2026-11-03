import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import { configureApi, ApiError } from '../services/api'
import { buildLoginMessage, encodeSignature, login, requestChallenge } from './auth.api'
import { clearSession, getTokenExpiry, loadSession, saveSession } from './auth.storage'
import type { Session, SignInStep } from './auth.types'
import { AuthContext, type AuthContextValue } from './useAuth.ts'

const MAX_TIMEOUT = 2 ** 31 - 1

function toMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) {
    if (/reject|denied|cancel/i.test(e.message)) return 'You cancelled the signature request.'
    return e.message
  }
  return 'Something went wrong. Please try again.'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { publicKey, signMessage } = useWallet()

  const [session, setSession] = useState<Session | null>(() => loadSession())
  const [step, setStep] = useState<SignInStep>('idle')
  const [error, setError] = useState<string | null>(null)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const sessionRef = useRef<Session | null>(session)

  const applySession = useCallback((next: Session | null) => {
    sessionRef.current = next
    setSession(next)
    if (next) saveSession(next)
    else clearSession()
  }, [])

  useLayoutEffect(() => {
    configureApi({
      getToken: () => sessionRef.current?.token ?? null,
      onUnauthorized: () => applySession(null),
    })
  }, [applySession])


  useEffect(() => {
    if (!session) return
    const exp = getTokenExpiry(session.token)
    if (exp === null) return
    const ms = exp - Date.now()
    if (ms <= 0) {
      applySession(null)
      return
    }
    const id = setTimeout(() => applySession(null), Math.min(ms, MAX_TIMEOUT))
    return () => clearTimeout(id)
  }, [session, applySession])

  // User switched to a different account in their wallet: the session no longer matches.
  // A plain disconnect keeps the session; wallet-dependent actions will ask to reconnect.
  useEffect(() => {
    if (session && publicKey && publicKey.toBase58() !== session.user.address) {
      applySession(null)
    }
  }, [session, publicKey, applySession])

  const signIn = useCallback(async () => {
    if (!publicKey || !signMessage) {
      setError('Connect a wallet that supports message signing.')
      return
    }
    const address = publicKey.toBase58()
    setError(null)

    try {
      setStep('requesting-challenge')
      const { nonce } = await requestChallenge(address)
      const message = buildLoginMessage(nonce)

      setStep('awaiting-signature')
      const signature = await signMessage(new TextEncoder().encode(message))

      setStep('verifying')
      const res = await login({ address, signature: encodeSignature(signature), message })

      applySession({ token: res.token, user: res.user })
      setAuthModalOpen(false)
    } catch (e) {
      setError(toMessage(e))
    } finally {
      setStep('idle')
    }
  }, [publicKey, signMessage, applySession])

  const signOut = useCallback(() => applySession(null), [applySession])
  const openAuthModal = useCallback(() => setAuthModalOpen(true), [])
  const closeAuthModal = useCallback(() => setAuthModalOpen(false), [])
  const clearError = useCallback(() => setError(null), [])

  const value = useMemo<AuthContextValue>(
    () => ({
      status: session ? 'authenticated' : 'guest',
      user: session?.user ?? null,
      step,
      error,
      authModalOpen,
      signIn,
      signOut,
      openAuthModal,
      closeAuthModal,
      clearError,
    }),
    [session, step, error, authModalOpen, signIn, signOut, openAuthModal, closeAuthModal, clearError],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
