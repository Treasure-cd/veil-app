import type { Session } from './auth.types'

const KEY = 'veil_session'

// Returns the JWT `exp` claim in milliseconds, or null if it can't be read.
export function getTokenExpiry(token: string): number | null {
  try {
    const payload = token.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const { exp } = JSON.parse(json)
    return typeof exp === 'number' ? exp * 1000 : null
  } catch {
    return null
  }
}

function isExpired(token: string) {
  const exp = getTokenExpiry(token)
  return exp === null || exp <= Date.now()
}

export function saveSession(session: Session) {
  try {
    localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    // storage unavailable (private mode, quota): session lasts until refresh
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const session = JSON.parse(raw) as Session
    if (!session?.token || !session?.user?.address || isExpired(session.token)) {
      clearSession()
      return null
    }
    return session
  } catch {
    return null
  }
}
