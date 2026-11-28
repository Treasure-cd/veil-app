export interface AuthUser {
  id: string
  address: string
  hasWallet?: boolean
  phoneMasked?: string | null
  isAdmin?: boolean
  createdAt: string
  updatedAt: string
}

export interface Session {
  token: string
  user: AuthUser
  authMethod?: 'wallet' | 'whatsapp'
}

export type AuthStatus = 'guest' | 'authenticated'

export type AuthTab = 'wallet' | 'whatsapp'

export type SignInStep =
  | 'idle'
  | 'requesting-challenge'
  | 'awaiting-signature'
  | 'verifying'

export interface ChallengeResponse {
  nonce: string
}

export interface LoginPayload {
  address: string
  signature: string
  message: string
}

export interface LoginResponse {
  token: string
  user: AuthUser
}

export interface WhatsAppAuthChallengeResponse {
  challengeToken: string
  code: string
  expiresAt: string
  joinUrl: string | null
  sendUrl: string | null
}

export type WhatsAppAuthPollResponse =
  | { status: 'pending' }
  | { status: 'verified'; token: string; user: AuthUser }
