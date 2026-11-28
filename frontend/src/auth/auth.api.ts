import bs58 from 'bs58'
import { api } from '../services/api'
import type { AuthUser, ChallengeResponse, LoginPayload, LoginResponse } from './auth.types'

export const requestChallenge = (address: string) =>
  api<ChallengeResponse>('/v1/auth/challenge', {
    method: 'POST',
    body: JSON.stringify({ address }),
  })

export const login = (payload: LoginPayload) =>
  api<LoginResponse>('/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const registerEmail = (email: string, password: string) =>
  api<LoginResponse>('/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

export const loginEmail = (email: string, password: string) =>
  api<LoginResponse>('/v1/auth/login-email', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

export const fetchMe = () => api<AuthUser>('/v1/auth/me')

export const buildLoginMessage = (nonce: string) =>
  `Sign this message to login to Veil: ${nonce}`

export const encodeSignature = (signature: Uint8Array) => bs58.encode(signature)
