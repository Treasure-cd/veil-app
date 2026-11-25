import { api } from './api'

export type FiatPaymentFlow = 'checkout' | 'payout'
export type FiatPaymentStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'expired'
  | 'reversed'
export type FeeBearer = 'customer' | 'merchant'

export interface FiatPayment {
  id: string
  paymentIntentId: string | null
  flow: FiatPaymentFlow
  reference: string
  currency: string
  amount: string
  fee: string | null
  amountPayable: string | null
  feeBearer: FeeBearer | null
  accountType: string | null
  bankName: string | null
  accountName: string | null
  accountNumber: string | null
  status: FiatPaymentStatus
  paymentOutcome: string | null
  receivedAmount: string | null
  description: string | null
  expiresAt: string | null
  completedAt: string | null
  failedAt: string | null
  reversedAt: string | null
  createdAt: string | null
  userId?: string
  fossapayId?: string | null
  transactionId?: string | null
  providerReference?: string | null
  settlementAmount?: string | null
  totalDebited?: string | null
  route?: string | null
  bankCode?: string | null
  failureReason?: string | null
  updatedAt?: string | null
}

export interface SupportedBank {
  bankname: string
  bankcode: string
}

export interface BankNameEnquiryResult {
  accountNumber: string
  accountName: string
  sessionId?: string | null
}

export interface FiatFeeQuote {
  amount: number
  currency: string
  feeAmount: number
  total: number
}

export interface CreateFiatPayoutInput {
  amountNgn: number
  bankCode: string
  bankName: string
  accountNumber: string
  accountName: string
  remarks?: string
  paymentIntentId?: string
  idempotencyKey?: string
}

export function listFiatPayments(flow?: FiatPaymentFlow) {
  const query = flow ? `?flow=${encodeURIComponent(flow)}` : ''
  return api<FiatPayment[]>(`/v1/payments/fiat${query}`)
}

export function listFiatBanks() {
  return api<SupportedBank[]>('/v1/payments/fiat/banks')
}

export function verifyBankAccount(bankCode: string, accountNumber: string) {
  return api<BankNameEnquiryResult>('/v1/payments/fiat/bank-name-enquiry', {
    method: 'POST',
    body: JSON.stringify({ bankCode, accountNumber }),
  })
}

export function getFiatTransferFee(amount: number) {
  return api<FiatFeeQuote>(`/v1/payments/fiat/fee?amount=${encodeURIComponent(String(amount))}`)
}

export function createFiatPayout(payload: CreateFiatPayoutInput) {
  return api<FiatPayment>('/v1/payments/fiat/payouts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function reconcileFiatPayment(fiatId: string) {
  return api<FiatPayment>(`/v1/payments/fiat/${encodeURIComponent(fiatId)}/reconcile`, {
    method: 'POST',
  })
}

export function expireFiatPayment(fiatId: string) {
  return api<FiatPayment>(`/v1/payments/fiat/${encodeURIComponent(fiatId)}/expire`, {
    method: 'POST',
  })
}

export function createIntentFiatCheckout(intentId: string) {
  return api<FiatPayment>(`/v1/payments/intents/${encodeURIComponent(intentId)}/fiat-checkout`, {
    method: 'POST',
  })
}

export function reconcileIntentFiatCheckout(intentId: string) {
  return api<FiatPayment>(
    `/v1/payments/intents/${encodeURIComponent(intentId)}/fiat-checkout/reconcile`,
    { method: 'POST' },
  )
}

export function getFiatStatusPresentation(
  status: FiatPaymentStatus,
  outcome?: string | null,
): { label: string; className: string } {
  switch (status) {
    case 'completed':
      return { label: 'Completed', className: 'bg-emerald-100 text-emerald-800' }
    case 'processing':
      return { label: 'Processing', className: 'bg-primary/10 text-primary' }
    case 'pending':
      return { label: 'Awaiting transfer', className: 'bg-amber-100 text-amber-800' }
    case 'expired':
      return { label: 'Expired', className: 'bg-foreground/10 text-foreground/70' }
    case 'reversed':
      return { label: 'Reversed', className: 'bg-amber-100 text-amber-900' }
    case 'failed':
      return {
        label: outcome === 'underpaid'
          ? 'Underpaid'
          : outcome === 'overpaid'
            ? 'Overpaid'
            : 'Failed',
        className: 'bg-red-100 text-red-700',
      }
  }
}
