export interface AuthUser {
  id: string
  address: string
  createdAt: string
  updatedAt: string
}

export interface Session {
  token: string
  user: AuthUser
}

export type AuthStatus = 'guest' | 'authenticated'

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
