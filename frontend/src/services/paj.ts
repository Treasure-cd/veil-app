import { api } from './api'

export type SettlementTarget = 'crypto' | 'fiat'
export type PajOrderStatus = 'INIT' | 'PROCESSING' | 'COMPLETED' | 'ERROR'

export interface PajBank {
  id: string
  name: string
  country: string
  code: string
  logo?: string | null
}

export interface MerchantBankAccount {
  id: string
  bankName: string
  isDefault: boolean
  userId?: string
  pajAccountId?: string
  bankCode?: string
  accountNumber?: string
  accountName?: string
  solanaAddress?: string
  evmAddress?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface PajTokenInfo {
  symbol: string
  name: string
  mint: string
  decimals: number
}

export interface PajRates {
  onRampRate?: { rate: number; targetCurrency: string }
  offRampRate?: { rate: number; targetCurrency: string }
  tokens: PajTokenInfo[]
}

export interface PajOfframpOrder {
  id: string
  paymentIntentId: string | null
  chain: string
  mint: string
  tokenSymbol: string
  tokenDecimals: number
  depositAddress: string
  tokenAmount: string | null
  fiatAmount: string | null
  currency: string
  rate: string | null
  feeUsdc: string | null
  status: PajOrderStatus
  txSignature: string | null
  narration: string | null
  expiresAt: string | null
  createdAt: string | null
  pajOrderId?: string | null
  bankAccountId?: string | null
  bankCode?: string | null
  bankName?: string | null
  accountNumber?: string | null
  accountName?: string | null
  failureReason?: string | null
}

export function listPajBanks() {
  return api<PajBank[]>('/v1/payments/paj/banks')
}

export function getPajRates() {
  return api<PajRates>('/v1/payments/paj/rates')
}

export function listMerchantBankAccounts() {
  return api<MerchantBankAccount[]>('/v1/payments/paj/bank-accounts')
}

export function registerMerchantBankAccount(
  bankCode: string,
  accountNumber: string,
  makeDefault = true,
) {
  return api<MerchantBankAccount>('/v1/payments/paj/bank-accounts', {
    method: 'POST',
    body: JSON.stringify({ bankCode, accountNumber, makeDefault }),
  })
}

export function deleteMerchantBankAccount(accountId: string) {
  return api<{ ok: boolean }>(`/v1/payments/paj/bank-accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  })
}

export function listPajOfframps() {
  return api<PajOfframpOrder[]>('/v1/payments/paj/offramps')
}

export function reconcilePajOfframp(orderId: string) {
  return api<PajOfframpOrder>(
    `/v1/payments/paj/offramps/${encodeURIComponent(orderId)}/reconcile`,
    { method: 'POST' },
  )
}

export function createIntentPajOfframp(intentId: string, token: string) {
  return api<PajOfframpOrder>(
    `/v1/payments/intents/${encodeURIComponent(intentId)}/paj-offramp`,
    {
      method: 'POST',
      body: JSON.stringify({ token }),
    },
  )
}

export function reconcileIntentPajOfframp(intentId: string) {
  return api<PajOfframpOrder>(
    `/v1/payments/intents/${encodeURIComponent(intentId)}/paj-offramp/reconcile`,
    { method: 'POST' },
  )
}

export function getPajStatusPresentation(status: PajOrderStatus): {
  label: string
  className: string
} {
  switch (status) {
    case 'COMPLETED':
      return { label: 'Paid to bank', className: 'bg-emerald-100 text-emerald-800' }
    case 'PROCESSING':
      return { label: 'Converting to NGN', className: 'bg-primary/10 text-primary' }
    case 'INIT':
      return { label: 'Awaiting token deposit', className: 'bg-amber-100 text-amber-800' }
    case 'ERROR':
      return { label: 'Offramp error', className: 'bg-red-100 text-red-700' }
  }
}
