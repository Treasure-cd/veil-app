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
import { buildLoginMessage, encodeSignature, fetchMe, login, requestChallenge } from './auth.api'
import { clearSession, getTokenExpiry, loadSession, saveSession } from './auth.storage'
import type { LoginResponse, Session, SignInStep } from './auth.types'
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

/** Returns true if the account has no connected Solana wallet (WhatsApp identity). */
function isNonWalletSession(session: Session | null): boolean {
  if (!session) return false
  return (
    session.authMethod === 'whatsapp' ||
    session.user.hasWallet === false ||
    Boolean(session.user.address?.startsWith('whatsapp:'))
  )
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { publicKey, signMessage, connecting, disconnect } = useWallet()

  const [session, setSession] = useState<Session | null>(() => loadSession())
  const [step, setStep] = useState<SignInStep>('idle')
  const [error, setError] = useState<string | null>(null)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const sessionRef = useRef<Session | null>(session)
  const lastConnectedAddressRef = useRef<string | null>(publicKey?.toBase58() ?? null)

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
    if (exp === null) {
      applySession(null)
      return
    }
    const ms = exp - Date.now()
    if (ms <= 0) {
      applySession(null)
      return
    }
    const id = setTimeout(() => applySession(null), Math.min(ms, MAX_TIMEOUT))
    return () => clearTimeout(id)
  }, [session, applySession])

  // Sync current user profile (e.g. admin role grants) in background for existing sessions.
  const syncedTokenRef = useRef<string | null>(null)
  useEffect(() => {
    const token = session?.token
    if (!token || syncedTokenRef.current === token) return
    syncedTokenRef.current = token
    let cancelled = false
    void fetchMe()
      .then((freshUser) => {
        if (cancelled) return
        const latest = sessionRef.current
        if (!latest || latest.token !== token) return
        if (
          latest.user.isAdmin !== freshUser.isAdmin ||
          latest.user.updatedAt !== freshUser.updatedAt ||
          latest.user.phoneMasked !== freshUser.phoneMasked ||
          latest.user.hasWallet !== freshUser.hasWallet
        ) {
          applySession({ ...latest, user: freshUser })
        }
      })
      .catch(() => {
        // Ignore transient offline errors; 401 is handled via configureApi.onUnauthorized
      })
    return () => {
      cancelled = true
    }
  }, [session?.token, applySession])

  // On reload, there may be no public key until the wallet adapter restores its connection.
  // Keep the persisted session during that gap, but clear it if an active wallet disconnects
  // or changes to an address that does not own this session.
  // For WhatsApp sessions / non-wallet accounts, skip wallet-binding logic.
  useEffect(() => {
    if (connecting || isNonWalletSession(session)) return

    const address = publicKey?.toBase58() ?? null
    if (address) lastConnectedAddressRef.current = address
    if (!session || address === session.user.address) return
    if (address !== null || lastConnectedAddressRef.current !== null) applySession(null)
  }, [session, publicKey, connecting, applySession])

  const signIn = useCallback(async () => {
    if (!publicKey || !signMessage) {
      setError('Connect a wallet that supports message signing.')
      return
    }
    const address = publicKey.toBase58()
    const currentSession = sessionRef.current
    const expiresAt = currentSession ? getTokenExpiry(currentSession.token) : null
    if (currentSession?.user.address === address && expiresAt !== null && expiresAt > Date.now()) {
      setAuthModalOpen(false)
      setError(null)
      return
    }
    setError(null)

    try {
      setStep('requesting-challenge')
      const { nonce } = await requestChallenge(address)
      const message = buildLoginMessage(nonce)

      setStep('awaiting-signature')
      const signature = await signMessage(new TextEncoder().encode(message))

      setStep('verifying')
      const res = await login({ address, signature: encodeSignature(signature), message })

      applySession({ token: res.token, user: res.user, authMethod: 'wallet' })
      setAuthModalOpen(false)
    } catch (e) {
      setError(toMessage(e))
    } finally {
      setStep('idle')
    }
  }, [publicKey, signMessage, applySession])

  const completeWhatsAppSignIn = useCallback(
    (res: LoginResponse) => {
      applySession({ token: res.token, user: res.user, authMethod: 'whatsapp' })
      setError(null)
      setAuthModalOpen(false)
    },
    [applySession],
  )

  const signOut = useCallback(() => applySession(null), [applySession])
  const disconnectWallet = useCallback(async () => {
    applySession(null)
    setError(null)
    setAuthModalOpen(false)
    try {
      await disconnect()
    } catch {
      setError('Veil signed out, but your wallet could not be disconnected. Try again in your wallet.')
    }
  }, [applySession, disconnect])
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
      completeWhatsAppSignIn,
      signOut,
      disconnectWallet,
      openAuthModal,
      closeAuthModal,
      clearError,
    }),
    [session, step, error, authModalOpen, signIn, completeWhatsAppSignIn, signOut, disconnectWallet, openAuthModal, closeAuthModal, clearError],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
