import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  ArrowsClockwise,
  ArrowSquareOut,
  CheckCircle,
  MagnifyingGlass,
  ShieldCheck,
  Trash,
  UserPlus,
  Warning,
  Wrench,
} from '@phosphor-icons/react'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'
import { Money } from '../components/ui/Money'
import { truncateAddress } from '../lib/format'
import { formatNgn } from '../lib/money'
import { solanaExplorerTxUrl } from '../lib/network'
import {
  getAdminFlowDetail,
  getAdminOverview,
  grantAdmin,
  listAdminFlows,
  listAdminPayroll,
  listAdmins,
  listUnlinkedFiat,
  reconcileAdminFlow,
  retryAdminPayout,
  revokeAdmin,
  verifySignatureRecovery,
  type AdminFlowDetail,
  type AdminFlowSummary,
  type AdminOverview,
  type AdminPayrollItem,
  type AdminUserItem,
  type VerifySignatureRecoveryResponse,
} from '../services/admin'
import type { FiatPayment } from '../services/fiat'

type AdminTab = 'flows' | 'payroll' | 'unlinked' | 'admins'

const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'anomalies', label: 'Anomalies' },
  { key: 'settling', label: 'Settling' },
  { key: 'settled', label: 'Settled' },
  { key: 'awaiting_claim', label: 'Awaiting claim' },
  { key: 'pending', label: 'Pending' },
  { key: 'expired', label: 'Expired' },
  { key: 'failed', label: 'Failed' },
] as const

const STATUS_BADGE: Record<string, string> = {
  settled: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300',
  settling: 'bg-primary/10 text-primary',
  awaiting_claim: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  pending: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  expired: 'bg-foreground/10 text-foreground/70',
  failed: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300',
}

const TRACE_BADGE: Record<string, string> = {
  ok: 'bg-emerald-500',
  warn: 'bg-amber-500',
  error: 'bg-red-500',
  info: 'bg-primary/60',
}

function formatDateTime(value: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-NG', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function AdminKpiCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <article className="rounded-panel border border-primary/10 bg-surface p-5">
      <p className="mb-2 text-xs font-medium text-foreground/50">{label}</p>
      {children}
    </article>
  )
}

export function Admin() {
  const { user } = useAuth()
  const [tab, setTab] = useState<AdminTab>('flows')

  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [flows, setFlows] = useState<AdminFlowSummary[]>([])
  const [flowsTotal, setFlowsTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [railFilter, setRailFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AdminFlowDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [payrollItems, setPayrollItems] = useState<AdminPayrollItem[]>([])
  const [unlinkedFiat, setUnlinkedFiat] = useState<(FiatPayment & { userAddress: string | null })[]>([])
  const [admins, setAdmins] = useState<AdminUserItem[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  // Signature recovery tool state
  const [recoverySig, setRecoverySig] = useState('')
  const [recoveryRail, setRecoveryRail] = useState<'direct' | 'paj' | 'umbra'>('direct')
  const [ignoreExpiry, setIgnoreExpiry] = useState(false)
  const [recoveryNote, setRecoveryNote] = useState('')
  const [dryRunResult, setDryRunResult] = useState<VerifySignatureRecoveryResponse | null>(null)

  // Add admin form state
  const [newAdminAddress, setNewAdminAddress] = useState('')
  const [newAdminNote, setNewAdminNote] = useState('')

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedQuery(searchQuery), 220)
    return () => window.clearTimeout(id)
  }, [searchQuery])

  const loadWorkspace = useCallback(async () => {
    if (!user?.isAdmin) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [ov, fl] = await Promise.all([
        getAdminOverview(),
        listAdminFlows({ status: statusFilter, rail: railFilter, q: debouncedQuery, limit: 80 }),
      ])
      setOverview(ov)
      setFlows(fl.items)
      setFlowsTotal(fl.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin overview.')
    } finally {
      setLoading(false)
    }
  }, [user?.isAdmin, statusFilter, railFilter, debouncedQuery])

  useEffect(() => {
    void loadWorkspace()
  }, [loadWorkspace])

  const loadTabExtras = useCallback(async () => {
    if (!user?.isAdmin) return
    try {
      if (tab === 'payroll') {
        const res = await listAdminPayroll()
        setPayrollItems(res.items)
      } else if (tab === 'unlinked') {
        const res = await listUnlinkedFiat()
        setUnlinkedFiat(res.items)
      } else if (tab === 'admins') {
        const res = await listAdmins()
        setAdmins(res.items)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load section data.')
    }
  }, [tab, user?.isAdmin])

  useEffect(() => {
    void loadTabExtras()
  }, [loadTabExtras])

  const inspectFlow = useCallback(async (intentId: string) => {
    setSelectedId(intentId)
    setDetailLoading(true)
    setDryRunResult(null)
    setActionFeedback(null)
    try {
      const data = await getAdminFlowDetail(intentId)
      setDetail(data)
      setRecoveryRail(data.primaryPaj ? 'paj' : data.receiveMode === 'private' ? 'umbra' : 'direct')
      setRecoverySig(data.fundSignature ?? data.primaryPaj?.txSignature ?? '')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load flow trace.')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  async function handleReconcile(intentId: string) {
    setActionBusy('reconcile')
    setActionFeedback(null)
    setError(null)
    try {
      const updated = await reconcileAdminFlow(intentId)
      setDetail(updated)
      setActionFeedback('Reconciled all payment rails and updated trace.')
      await loadWorkspace()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconciliation failed.')
    } finally {
      setActionBusy(null)
    }
  }

  async function handleRetryPayout(intentId: string) {
    setActionBusy('retry_payout')
    setActionFeedback(null)
    setError(null)
    try {
      const updated = await retryAdminPayout(intentId)
      setDetail(updated)
      setActionFeedback('Triggered fresh FossaPay settlement payout attempt.')
      await loadWorkspace()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Payout retry failed.')
    } finally {
      setActionBusy(null)
    }
  }

  async function handleVerifySignature(dryRun: boolean) {
    if (!detail || !recoverySig.trim()) return
    setActionBusy(dryRun ? 'verify_dry' : 'verify_apply')
    setActionFeedback(null)
    setError(null)
    try {
      const res = await verifySignatureRecovery(detail.id, {
        signature: recoverySig.trim(),
        rail: recoveryRail,
        pajOfframpOrderId: recoveryRail === 'paj' ? detail.primaryPaj?.id : undefined,
        dryRun,
        ignoreExpiryWindow: ignoreExpiry,
        note: recoveryNote.trim() || undefined,
      })
      setDryRunResult(res)
      setDetail(res.flow)
      if (res.applied) {
        setActionFeedback('Signature verified and applied to recover payment intent.')
        await loadWorkspace()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signature verification failed.')
    } finally {
      setActionBusy(null)
    }
  }

  async function handleGrantAdmin(e: React.FormEvent) {
    e.preventDefault()
    if (!newAdminAddress.trim()) return
    setActionBusy('grant_admin')
    setError(null)
    setActionFeedback(null)
    try {
      await grantAdmin(newAdminAddress.trim(), newAdminNote.trim() || undefined)
      setNewAdminAddress('')
      setNewAdminNote('')
      setActionFeedback('Admin access granted.')
      const res = await listAdmins()
      setAdmins(res.items)
      await loadWorkspace()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not grant admin role.')
    } finally {
      setActionBusy(null)
    }
  }

  async function handleRevokeAdmin(address: string) {
    setActionBusy(`revoke:${address}`)
    setError(null)
    setActionFeedback(null)
    try {
      await revokeAdmin(address)
      setActionFeedback(`Revoked admin role from ${truncateAddress(address)}.`)
      const res = await listAdmins()
      setAdmins(res.items)
      await loadWorkspace()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke admin role.')
    } finally {
      setActionBusy(null)
    }
  }

  if (!user?.isAdmin) {
    return (
      <section className="mx-auto max-w-xl rounded-panel border border-primary/10 bg-surface p-8 text-center">
        <ShieldCheck size={36} weight="duotone" className="mx-auto text-primary" />
        <h1 className="mt-3 text-2xl font-semibold text-primary">Admin access required</h1>
        <p className="mt-2 text-sm text-foreground/65">
          Wallet <span className="font-mono text-foreground">{user?.address ?? 'connected'}</span> is not authorized to view platform-wide fund traces.
        </p>
      </section>
    )
  }

  return (
    <div className="w-full space-y-6 pb-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-tight text-primary">Operations &amp; Fund Traces</h1>
            <span className="rounded-pill bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">
              Admin
            </span>
          </div>
          <p className="mt-1 text-sm text-foreground/60">
            Examine platform-wide NGN and Solana fund flows, inspect anomalies, and recover stuck payments.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            className="inline-flex flex-wrap rounded-pill border border-primary/10 bg-surface p-1 shadow-veil-sm"
            role="tablist"
            aria-label="Admin sections"
          >
            {(
              [
                { key: 'flows', label: 'Flows & Traces' },
                { key: 'payroll', label: 'Payroll Vaults' },
                { key: 'unlinked', label: 'Standalone Fiat' },
                { key: 'admins', label: 'Admins' },
              ] as const
            ).map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                onClick={() => setTab(item.key)}
                className={`rounded-pill px-3.5 py-1.5 text-xs font-semibold transition-colors ${
                  tab === item.key
                    ? 'bg-primary-action text-white'
                    : 'text-foreground/65 hover:text-primary'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <Button
            size="sm"
            variant="secondary"
            loading={loading}
            leftIcon={<ArrowsClockwise size={15} />}
            onClick={() => {
              void loadWorkspace()
              void loadTabExtras()
            }}
          >
            Refresh
          </Button>
        </div>
      </header>

      {error && (
        <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
          {error}
        </p>
      )}
      {actionFeedback && (
        <p role="status" className="rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950/40 dark:text-emerald-300">
          {actionFeedback}
        </p>
      )}

      {overview && (
        <section aria-label="Platform metrics" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <AdminKpiCard label="Total Platform Volume">
            <div className="font-mono text-2xl font-semibold tabular-nums text-primary">
              {formatNgn(overview.totalVolumeNgn)}
            </div>
            <p className="mt-1.5 text-xs text-foreground/50">
              {overview.totalIntents.toLocaleString()} payment requests · {overview.traceEventCount.toLocaleString()} trace events
            </p>
          </AdminKpiCard>

          <AdminKpiCard label="Settled vs In-Flight">
            <div className="font-mono text-2xl font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
              {formatNgn(overview.settledVolumeNgn)}
            </div>
            <p className="mt-1.5 text-xs text-foreground/50">
              {formatNgn(overview.inFlightVolumeNgn)} currently in flight ({overview.statusCounts.settling ?? 0} settling)
            </p>
          </AdminKpiCard>

          <AdminKpiCard label="Active Anomalies">
            <div className={`font-mono text-2xl font-semibold tabular-nums ${overview.anomalousIntentCount > 0 ? 'text-red-600 dark:text-red-400' : 'text-primary'}`}>
              {overview.anomalousIntentCount.toLocaleString()}
            </div>
            <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-foreground/50">
              <span>Drifts or stuck payouts</span>
              {overview.anomalousIntentCount > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setTab('flows')
                    setStatusFilter('anomalies')
                  }}
                  className="font-semibold text-primary hover:underline"
                >
                  View anomalies
                </button>
              )}
            </div>
          </AdminKpiCard>

          <AdminKpiCard label="Rails &amp; Governance">
            <div className="font-mono text-2xl font-semibold tabular-nums text-primary">
              {overview.merchantCount.toLocaleString()} wallets
            </div>
            <p className="mt-1.5 text-xs text-foreground/50">
              Paj {overview.railCounts.paj ?? 0} · FossaPay {overview.railCounts.fossapay ?? 0} · Solana {overview.railCounts.crypto ?? 0} · {overview.adminCount} admins
            </p>
          </AdminKpiCard>
        </section>
      )}

      {tab === 'flows' && (
        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr] xl:items-start">
          {/* Left: Filter + Flows list */}
          <section className="rounded-panel border border-primary/10 bg-surface">
            <div className="space-y-3 border-b border-primary/10 p-4 sm:p-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative min-w-0 flex-1 basis-56">
                  <MagnifyingGlass size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground/40" />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search ref, ID, wallet, signature, FossaPay/Paj ref..."
                    className="h-10 w-full rounded-card border border-primary/15 bg-background pl-9 pr-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                  />
                </div>
                <select
                  aria-label="Filter by rail"
                  value={railFilter}
                  onChange={(e) => setRailFilter(e.target.value)}
                  className="h-10 rounded-card border border-primary/15 bg-background px-3 text-xs font-medium text-foreground outline-none focus:border-primary/40"
                >
                  <option value="all">All rails</option>
                  <option value="paj">Paj Cash</option>
                  <option value="fossapay">FossaPay</option>
                  <option value="crypto">Direct Solana</option>
                  <option value="unpaid">Unpaid</option>
                </select>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {STATUS_FILTERS.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => setStatusFilter(f.key)}
                    className={`rounded-pill px-3 py-1 text-xs font-medium transition-colors ${
                      statusFilter === f.key
                        ? 'bg-primary text-white'
                        : 'bg-primary/5 text-foreground/70 hover:bg-primary/10 hover:text-primary'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
                <span className="ml-auto self-center text-xs text-foreground/45">
                  {flowsTotal.toLocaleString()} matching
                </span>
              </div>
            </div>

            {flows.length === 0 ? (
              <p className="px-6 py-12 text-center text-sm text-foreground/50">
                No payment flows match the selected filters.
              </p>
            ) : (
              <ul className="divide-y divide-primary/5">
                {flows.map((flow) => {
                  const isSelected = selectedId === flow.id
                  return (
                    <li key={flow.id}>
                      <button
                        type="button"
                        onClick={() => void inspectFlow(flow.id)}
                        className={`flex w-full flex-wrap items-center justify-between gap-3 px-4 py-3.5 text-left transition-colors sm:px-5 ${
                          isSelected ? 'bg-primary/[0.07]' : 'hover:bg-primary/[0.03]'
                        }`}
                      >
                        <div className="min-w-0 flex-1 basis-52">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-sm font-semibold text-foreground">
                              {flow.memo || flow.merchantRef}
                            </span>
                            <span className={`inline-flex rounded-pill px-2 py-0.5 text-[11px] font-medium ${STATUS_BADGE[flow.settlementStatus] ?? 'bg-foreground/10 text-foreground/70'}`}>
                              {flow.settlementStatus.replace('_', ' ')}
                            </span>
                            {flow.anomalies.length > 0 && (
                              <span className="inline-flex items-center gap-1 rounded-pill bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700 dark:bg-red-500/15 dark:text-red-300">
                                <Warning size={12} weight="fill" />
                                {flow.anomalies.length} anomaly
                              </span>
                            )}
                          </div>
                          <p className="mt-1 truncate text-xs text-foreground/55">
                            <span className="font-mono">{flow.merchantRef}</span>
                            {' · '}
                            <span>{flow.settlementTarget.toUpperCase()}</span>
                            {flow.paidVia ? ` · via ${flow.paidVia}` : ''}
                            {flow.merchantAddress ? ` · ${truncateAddress(flow.merchantAddress)}` : ''}
                            {' · '}
                            <span>{flow.traceCount} events</span>
                          </p>
                        </div>

                        <div className="ml-auto flex shrink-0 items-center gap-3">
                          <Money
                            amountNgn={flow.amountNgn}
                            tokenAmount={flow.tokenAmount}
                            token={flow.token}
                            align="right"
                            primaryClassName="text-sm font-semibold text-primary"
                          />
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          {/* Right: Flow Inspector & Recovery */}
          <aside className="rounded-panel border border-primary/10 bg-surface p-5 xl:sticky xl:top-20 sm:p-6">
            {detailLoading ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-6 w-2/3 rounded bg-primary/10" />
                <div className="h-24 rounded-card bg-primary/5" />
                <div className="h-44 rounded-card bg-primary/5" />
              </div>
            ) : !detail ? (
              <div className="py-12 text-center">
                <Wrench size={32} weight="duotone" className="mx-auto text-primary/60" />
                <h2 className="mt-3 text-base font-semibold text-primary">Select a payment flow</h2>
                <p className="mt-1 text-xs leading-relaxed text-foreground/55">
                  Click any payment on the left to inspect its multi-rail trail, trace events, webhooks, and recovery tools.
                </p>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-primary/10 pb-4">
                  <div className="min-w-0">
                    <p className="font-mono text-xs text-foreground/50">{detail.id}</p>
                    <h2 className="mt-0.5 truncate text-lg font-semibold text-primary">
                      {detail.memo || detail.merchantRef}
                    </h2>
                    <p className="mt-1 text-xs text-foreground/60">
                      Status: <span className="font-semibold text-foreground">{detail.intentStatus}</span>
                      {' · '}Target: <span className="uppercase">{detail.settlementTarget}</span>
                      {detail.paidVia ? ` · Paid via ${detail.paidVia}` : ''}
                    </p>
                  </div>
                  <Money
                    amountNgn={detail.amountNgn}
                    tokenAmount={detail.tokenAmount}
                    token={detail.token}
                    align="right"
                    primaryClassName="text-lg font-semibold text-primary"
                  />
                </div>

                {/* Anomaly alerts */}
                {detail.anomalies.length > 0 && (
                  <div className="space-y-2 rounded-card border border-red-200 bg-red-50/70 p-3.5 dark:border-red-500/30 dark:bg-red-950/30">
                    <p className="flex items-center gap-1.5 text-xs font-semibold text-red-700 dark:text-red-300">
                      <Warning size={15} weight="fill" />
                      Detected anomalies
                    </p>
                    {detail.anomalies.map((a, idx) => (
                      <p key={`${a.code}-${idx}`} className="text-xs leading-relaxed text-red-800 dark:text-red-200">
                        <span className="font-mono font-semibold">[{a.code}]</span> {a.message}
                      </p>
                    ))}
                  </div>
                )}

                {/* Safe Recovery Actions */}
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={actionBusy === 'reconcile'}
                    disabled={Boolean(actionBusy)}
                    leftIcon={<ArrowsClockwise size={14} />}
                    onClick={() => void handleReconcile(detail.id)}
                  >
                    Reconcile All Rails
                  </Button>
                  {detail.settlementTarget === 'fiat' &&
                    detail.checkouts.some((c) => c.status === 'completed') && (
                      <Button
                        size="sm"
                        loading={actionBusy === 'retry_payout'}
                        disabled={Boolean(actionBusy)}
                        onClick={() => void handleRetryPayout(detail.id)}
                      >
                        Retry FossaPay Payout
                      </Button>
                    )}
                </div>

                {/* Addresses & Bank Destination */}
                <div className="grid gap-2.5 rounded-card bg-background p-3.5 text-xs">
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="text-foreground/50">Merchant wallet</span>
                    <span className="font-mono text-foreground">{detail.merchantAddress ?? '—'}</span>
                  </div>
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="text-foreground/50">Destination address</span>
                    <span className="font-mono text-foreground">{detail.recipientAddress}</span>
                  </div>
                  {detail.bankAccount && (
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="text-foreground/50">Merchant bank</span>
                      <span className="font-medium text-foreground">
                        {detail.bankAccount.bankName} · {detail.bankAccount.accountNumber} ({detail.bankAccount.accountName})
                      </span>
                    </div>
                  )}
                  {detail.fundSignature && (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-foreground/50">Fund signature</span>
                      <a
                        href={solanaExplorerTxUrl(detail.fundSignature)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-mono text-primary hover:underline"
                      >
                        {truncateAddress(detail.fundSignature, 8)}
                        <ArrowSquareOut size={12} />
                      </a>
                    </div>
                  )}
                </div>

                {/* On-chain signature inspection / recovery */}
                <div className="space-y-3 rounded-card border border-primary/15 bg-background/60 p-3.5">
                  <p className="text-xs font-semibold text-primary">On-chain Signature Verification &amp; Recovery</p>
                  <input
                    type="text"
                    value={recoverySig}
                    onChange={(e) => setRecoverySig(e.target.value)}
                    placeholder="Solana transaction signature..."
                    className="h-9 w-full rounded-card border border-primary/15 bg-surface px-3 font-mono text-xs outline-none focus:border-primary/40"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label="Recovery verification rail"
                      value={recoveryRail}
                      onChange={(e) => setRecoveryRail(e.target.value as 'direct' | 'paj' | 'umbra')}
                      className="h-9 rounded-card border border-primary/15 bg-surface px-2.5 text-xs"
                    >
                      <option value="direct">Direct wallet</option>
                      <option value="paj">Paj deposit</option>
                      <option value="umbra">Umbra private</option>
                    </select>
                    <label className="inline-flex items-center gap-1.5 text-xs text-foreground/70">
                      <input
                        type="checkbox"
                        checked={ignoreExpiry}
                        onChange={(e) => setIgnoreExpiry(e.target.checked)}
                        className="accent-primary"
                      />
                      Ignore expiry window
                    </label>
                  </div>
                  <input
                    type="text"
                    value={recoveryNote}
                    onChange={(e) => setRecoveryNote(e.target.value)}
                    placeholder="Audit note (ticket / reason)..."
                    className="h-9 w-full rounded-card border border-primary/15 bg-surface px-3 text-xs outline-none focus:border-primary/40"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={actionBusy === 'verify_dry'}
                      disabled={!recoverySig.trim() || Boolean(actionBusy)}
                      onClick={() => void handleVerifySignature(true)}
                    >
                      Dry-run verify
                    </Button>
                    <Button
                      size="sm"
                      loading={actionBusy === 'verify_apply'}
                      disabled={!recoverySig.trim() || Boolean(actionBusy)}
                      onClick={() => void handleVerifySignature(false)}
                    >
                      Verify &amp; apply recovery
                    </Button>
                  </div>
                  {dryRunResult && (
                    <div className="rounded-card bg-surface p-2.5 text-xs text-foreground/80">
                      <p>
                        With memo: <strong>{dryRunResult.matchedWithMemo ? 'Matched' : 'No'}</strong> · Amount/dest only:{' '}
                        <strong>{dryRunResult.matchedWithoutMemo ? 'Matched' : 'No'}</strong>
                      </p>
                      {dryRunResult.duplicateIntentId && (
                        <p className="mt-1 text-red-600 dark:text-red-400">
                          Already recorded on intent: <span className="font-mono">{dryRunResult.duplicateIntentId}</span>
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Rail Records Summary */}
                {(detail.checkouts.length > 0 || detail.payouts.length > 0 || detail.pajOrders.length > 0) && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-foreground/50">Rail records</p>
                    <div className="space-y-2 text-xs">
                      {detail.checkouts.map((c) => (
                        <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card bg-background px-3 py-2">
                          <span>
                            FossaPay Checkout <span className="font-mono">{c.reference}</span>
                          </span>
                          <span className="font-semibold capitalize">{c.status} · ₦{c.amount}</span>
                        </div>
                      ))}
                      {detail.payouts.map((p) => (
                        <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card bg-background px-3 py-2">
                          <span>
                            FossaPay Payout <span className="font-mono">{p.reference}</span>
                            {p.failureReason ? ` (${p.failureReason})` : ''}
                          </span>
                          <span className="font-semibold capitalize">{p.status} · ₦{p.amount}</span>
                        </div>
                      ))}
                      {detail.pajOrders.map((o) => (
                        <div key={o.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card bg-background px-3 py-2">
                          <span>
                            Paj Cash <span className="font-mono">{o.pajOrderId ?? truncateAddress(o.depositAddress)}</span>
                          </span>
                          <span className="font-semibold">
                            {o.status} · {o.tokenAmount} {o.tokenSymbol}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Trace Timeline */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-foreground/50">
                    Audit trace timeline ({detail.traces.length})
                  </p>
                  {detail.traces.length === 0 ? (
                    <p className="text-xs text-foreground/45">No trace events recorded for this legacy payment.</p>
                  ) : (
                    <ol className="space-y-2.5 border-l border-primary/15 pl-3.5">
                      {detail.traces.map((t) => (
                        <li key={t.id} className="relative">
                          <span
                            className={`absolute -left-[1.15rem] top-1.5 size-2 rounded-full ${TRACE_BADGE[t.status] ?? TRACE_BADGE.info}`}
                            aria-hidden="true"
                          />
                          <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                            <span className="font-semibold text-foreground">{t.summary}</span>
                            <span className="font-mono text-[11px] text-foreground/45">{formatDateTime(t.createdAt)}</span>
                          </div>
                          <p className="mt-0.5 font-mono text-[11px] text-foreground/55">
                            {t.source}/{t.eventType}
                            {t.actorAddress ? ` · by ${truncateAddress(t.actorAddress)}` : ''}
                          </p>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              </div>
            )}
          </aside>
        </div>
      )}

      {tab === 'payroll' && (
        <section className="overflow-hidden rounded-panel border border-primary/10 bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-primary/10 bg-primary/[0.03] text-xs uppercase text-foreground/55">
                <tr>
                  <th className="px-4 py-3 font-medium">Payroll group</th>
                  <th className="px-4 py-3 font-medium">Employer</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Recipients</th>
                  <th className="px-4 py-3 font-medium">Total</th>
                  <th className="px-4 py-3 font-medium">Signatures</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-primary/5">
                {payrollItems.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-foreground/50">
                      No payroll groups recorded yet.
                    </td>
                  </tr>
                ) : (
                  payrollItems.map((group) => (
                    <tr key={group.id}>
                      <td className="px-4 py-3">
                        <p className="font-medium text-foreground">{group.title}</p>
                        <p className="font-mono text-xs text-foreground/50">{group.employerRef}</p>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-foreground/75">
                        {group.employerAddress ? truncateAddress(group.employerAddress) : '—'}
                      </td>
                      <td className="px-4 py-3 capitalize">{group.status}</td>
                      <td className="px-4 py-3">{group.recipientCount}</td>
                      <td className="px-4 py-3">
                        <Money
                          amountNgn={group.totalAmountNgn}
                          tokenAmount={group.totalAmountToken}
                          token={group.token}
                          primaryClassName="text-sm font-semibold text-primary"
                        />
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <div className="flex flex-wrap gap-2">
                          {group.vaultSignature && (
                            <a
                              href={solanaExplorerTxUrl(group.vaultSignature)}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-primary hover:underline"
                            >
                              Vault <ArrowSquareOut size={12} />
                            </a>
                          )}
                          {group.releaseSignature && (
                            <a
                              href={solanaExplorerTxUrl(group.releaseSignature)}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-emerald-600 hover:underline dark:text-emerald-400"
                            >
                              Release <ArrowSquareOut size={12} />
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'unlinked' && (
        <section className="overflow-hidden rounded-panel border border-primary/10 bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-primary/10 bg-primary/[0.03] text-xs uppercase text-foreground/55">
                <tr>
                  <th className="px-4 py-3 font-medium">Flow</th>
                  <th className="px-4 py-3 font-medium">Reference</th>
                  <th className="px-4 py-3 font-medium">Merchant</th>
                  <th className="px-4 py-3 font-medium">Bank</th>
                  <th className="px-4 py-3 font-medium">Amount</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-primary/5">
                {unlinkedFiat.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-foreground/50">
                      No standalone fiat payouts or checkouts without a payment intent.
                    </td>
                  </tr>
                ) : (
                  unlinkedFiat.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 capitalize font-medium">{item.flow}</td>
                      <td className="px-4 py-3 font-mono text-xs">{item.reference}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {item.userAddress ? truncateAddress(item.userAddress) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {item.bankName ?? '—'} {item.accountNumber ? `· ${item.accountNumber}` : ''}
                      </td>
                      <td className="px-4 py-3 font-mono font-semibold text-primary">
                        {formatNgn(item.amount)}
                      </td>
                      <td className="px-4 py-3 capitalize">{item.status}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'admins' && (
        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <form onSubmit={(e) => void handleGrantAdmin(e)} className="space-y-4 rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-primary">Add admin wallet</h2>
            <p className="text-xs leading-relaxed text-foreground/60">
              Grant admin privileges to another Solana wallet so your support/ops team can inspect traces and run recovery actions.
            </p>
            <div className="space-y-1.5">
              <label htmlFor="new-admin-address" className="text-xs font-medium text-foreground/70">
                Solana wallet address
              </label>
              <input
                id="new-admin-address"
                type="text"
                required
                value={newAdminAddress}
                onChange={(e) => setNewAdminAddress(e.target.value)}
                placeholder="Base58 public key"
                className="h-10 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-xs outline-none focus:border-primary/40"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="new-admin-note" className="text-xs font-medium text-foreground/70">
                Role note (optional)
              </label>
              <input
                id="new-admin-note"
                type="text"
                value={newAdminNote}
                onChange={(e) => setNewAdminNote(e.target.value)}
                placeholder="e.g. Support Engineer"
                className="h-10 w-full rounded-card border border-primary/15 bg-background px-3 text-xs outline-none focus:border-primary/40"
              />
            </div>
            <Button
              type="submit"
              size="sm"
              loading={actionBusy === 'grant_admin'}
              disabled={!newAdminAddress.trim() || Boolean(actionBusy)}
              leftIcon={<UserPlus size={15} />}
            >
              Grant admin access
            </Button>
          </form>

          <section className="rounded-panel border border-primary/10 bg-surface">
            <div className="border-b border-primary/10 px-5 py-4">
              <h2 className="font-semibold text-primary">Authorized admins ({admins.length})</h2>
            </div>
            <ul className="divide-y divide-primary/5">
              {admins.map((a) => {
                const isSelf = a.address === user?.address
                const protectedWallet = a.isSeedAdmin || isSelf
                return (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate font-mono text-sm font-medium text-foreground">{a.address}</span>
                        {a.isSeedAdmin && (
                          <span className="inline-flex items-center gap-1 rounded-pill bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                            <CheckCircle size={12} weight="fill" />
                            Seed Admin
                          </span>
                        )}
                        {isSelf && (
                          <span className="rounded-pill bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300">
                            You
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-foreground/45">
                        Added {formatDateTime(a.createdAt)}
                      </p>
                    </div>
                    {!protectedWallet && (
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={actionBusy === `revoke:${a.address}`}
                        disabled={Boolean(actionBusy)}
                        leftIcon={<Trash size={14} />}
                        onClick={() => void handleRevokeAdmin(a.address)}
                      >
                        Revoke
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        </div>
      )}
    </div>
  )
}

export default Admin
