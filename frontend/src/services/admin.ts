import { api } from './api'
import type { FiatPayment } from './fiat'
import type { MerchantBankAccount, PaidViaRail, PajOfframpOrder } from './paj'

export interface FlowAnomaly {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  message: string
}

export interface PaymentTraceEvent {
  id: string
  paymentIntentId: string | null
  fiatPaymentId: string | null
  pajOrderId: string | null
  payrollGroupId: string | null
  source: string
  eventType: string
  status: 'info' | 'ok' | 'warn' | 'error' | string
  summary: string
  details: Record<string, unknown> | null
  actorAddress: string | null
  createdAt: string | null
}

export interface AdminOverview {
  network: string
  totalIntents: number
  totalVolumeNgn: string
  settledVolumeNgn: string
  inFlightVolumeNgn: string
  statusCounts: Record<string, number>
  railCounts: Record<string, number>
  anomalousIntentCount: number
  anomalyBreakdown: Record<string, number>
  unlinkedFiatCount: number
  payrollGroupCount: number
  merchantCount: number
  adminCount: number
  traceEventCount: number
}

export interface AdminFlowSummary {
  id: string
  merchantRef: string
  memo: string | null
  merchantAddress: string | null
  recipientAddress: string
  channel: string
  receiveMode: 'private' | 'public'
  settlementTarget: 'crypto' | 'fiat'
  allowFiatCheckout: boolean
  intentStatus: string
  failureReason: string | null
  paidVia: PaidViaRail | null
  settlementStatus: 'settled' | 'settling' | 'awaiting_claim' | 'pending' | 'expired' | 'failed'
  amountNgn: string | null
  token: string
  tokenAmount: string
  rateNgnPerToken: string | null
  fundSignature: string | null
  claimSignature: string | null
  bankAccount: MerchantBankAccount | null
  latestCheckout: FiatPayment | null
  latestPayout: FiatPayment | null
  primaryPaj: PajOfframpOrder | null
  anomalies: FlowAnomaly[]
  recommendedAction: string | null
  traceCount: number
  latestTrace: PaymentTraceEvent | null
  createdAt: string | null
  updatedAt: string | null
  expiresAt: string | null
}

export interface AdminFlowDetail extends AdminFlowSummary {
  checkouts: FiatPayment[]
  payouts: FiatPayment[]
  pajOrders: PajOfframpOrder[]
  webhookEvents: {
    eventId: string
    eventType: string
    reference: string | null
    receivedAt: string | null
  }[]
  traces: PaymentTraceEvent[]
}

export interface AdminFlowsResponse {
  total: number
  limit: number
  offset: number
  items: AdminFlowSummary[]
}

export interface VerifySignatureRecoveryResponse {
  dryRun: boolean
  applied: boolean
  matchedWithMemo: boolean
  matchedWithoutMemo: boolean
  duplicateIntentId: string | null
  targetAddress: string
  targetMint: string
  targetAtomic: string
  flow: AdminFlowDetail
}

export interface AdminPayrollItem {
  id: string
  employerAddress: string | null
  employerRef: string
  title: string
  token: string
  status: string
  recipientCount: number
  totalAmountNgn: string
  totalAmountToken: string
  vaultSignature: string | null
  releaseSignature: string | null
  failureReason: string | null
  releaseAt: string | null
  createdAt: string | null
}

export interface AdminUserItem {
  id: string
  address: string
  isAdmin: boolean
  isSeedAdmin: boolean
  createdAt: string | null
  updatedAt: string | null
}

export const getAdminOverview = () => api<AdminOverview>('/v1/admin/overview')

export const listAdminFlows = (params: {
  status?: string
  rail?: string
  q?: string
  limit?: number
  offset?: number
} = {}) => {
  const qs = new URLSearchParams()
  if (params.status && params.status !== 'all') qs.set('status', params.status)
  if (params.rail && params.rail !== 'all') qs.set('rail', params.rail)
  if (params.q?.trim()) qs.set('q', params.q.trim())
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return api<AdminFlowsResponse>(`/v1/admin/flows${suffix}`)
}

export const getAdminFlowDetail = (intentId: string) =>
  api<AdminFlowDetail>(`/v1/admin/flows/${intentId}`)

export const reconcileAdminFlow = (intentId: string, note?: string) =>
  api<AdminFlowDetail>(`/v1/admin/flows/${intentId}/reconcile`, {
    method: 'POST',
    body: JSON.stringify(note ? { note } : {}),
  })

export const verifySignatureRecovery = (
  intentId: string,
  payload: {
    signature: string
    rail: 'direct' | 'paj' | 'umbra'
    pajOfframpOrderId?: string
    dryRun: boolean
    ignoreExpiryWindow?: boolean
    note?: string
  },
) =>
  api<VerifySignatureRecoveryResponse>(`/v1/admin/flows/${intentId}/verify-signature`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const retryAdminPayout = (intentId: string, note?: string) =>
  api<AdminFlowDetail>(`/v1/admin/flows/${intentId}/retry-payout`, {
    method: 'POST',
    body: JSON.stringify(note ? { note } : {}),
  })

export const listAdminPayroll = () =>
  api<{ total: number; items: AdminPayrollItem[] }>('/v1/admin/payroll')

export const listUnlinkedFiat = () =>
  api<{ total: number; items: (FiatPayment & { userAddress: string | null })[] }>('/v1/admin/unlinked-fiat')

export const listAdmins = () => api<{ items: AdminUserItem[] }>('/v1/admin/admins')

export const grantAdmin = (address: string, note?: string) =>
  api<AdminUserItem>('/v1/admin/admins', {
    method: 'POST',
    body: JSON.stringify({ address, ...(note?.trim() ? { note: note.trim() } : {}) }),
  })

export const revokeAdmin = (address: string) =>
  api<AdminUserItem>(`/v1/admin/admins/${encodeURIComponent(address)}`, {
    method: 'DELETE',
  })
