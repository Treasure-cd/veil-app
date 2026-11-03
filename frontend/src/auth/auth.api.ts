import bs58 from 'bs58'
import { api } from '../services/api'
import type { ChallengeResponse, LoginPayload, LoginResponse } from './auth.types'

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

export const buildLoginMessage = (nonce: string) =>
  `Sign this message to login to Veil: ${nonce}`

export const encodeSignature = (signature: Uint8Array) => bs58.encode(signature)
