import bs58 from 'bs58'
import { api } from '../services/api'
import type {
  AuthUser,
  ChallengeResponse,
  LoginPayload,
  LoginResponse,
  WhatsAppAuthChallengeResponse,
  WhatsAppAuthPollResponse,
} from './auth.types'

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

export const startWhatsAppAuth = () =>
  api<WhatsAppAuthChallengeResponse>('/v1/auth/whatsapp/challenge', {
    method: 'POST',
  })

export const pollWhatsAppAuth = (challengeToken: string) =>
  api<WhatsAppAuthPollResponse>(
    `/v1/auth/whatsapp/poll/${encodeURIComponent(challengeToken)}`,
  )

export const fetchMe = () => api<AuthUser>('/v1/auth/me')

export const buildLoginMessage = (nonce: string) =>
  `Sign this message to login to Veil: ${nonce}`

export const encodeSignature = (signature: Uint8Array) => bs58.encode(signature)
