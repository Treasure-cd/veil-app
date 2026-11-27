import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { ArrowDownLeft, ArrowUpRight, Lightning, LockKey, PaperPlaneRight } from '@phosphor-icons/react'
import { api } from '../services/api'
import { reconcileIntent, type PaidViaRail } from '../services/paj'
import { Button } from '../components/ui/Button'
import { Money } from '../components/ui/Money'
import { formatNgn } from '../lib/money'

type SettlementStatus = 'settled' | 'settling' | 'awaiting_claim' | 'pending' | 'expired' | 'failed'

interface DashboardData {
  volume_30d_ngn: string
  volume_prev_30d_ngn: string
  volume_change_percent: string | null
  transactions_30d: number
  awaiting_claim_count: number
  awaiting_claim_ngn: string
  vault_locked_ngn: string
  avg_payment_ngn: string
  daily_volume: { date: string; amount_ngn: string }[]
  by_channel: Record<string, { total_ngn: string; count: number }>
  by_privacy: Record<'public' | 'private', { total_ngn: string; count: number }>
  recent_activity: {
    id: string
    title: string
    channel: string
    status: string
    settlement_target: 'crypto' | 'fiat'
    paid_via: PaidViaRail | null
    settlement_status: SettlementStatus
    paj_status: string | null
    amount_ngn: string
    token: string
    token_amount: string
    created_at: string
  }[]
}

const PAID_VIA_LABELS: Record<PaidViaRail, string> = {
  paj: 'via Paj',
  fossapay: 'via FossaPay',
  crypto: 'via Solana',
}

function getActivityStatusPresentation(
  status: SettlementStatus,
  settlementTarget: 'crypto' | 'fiat',
): { label: string; className: string } {
  switch (status) {
    case 'settled':
      return {
        label: settlementTarget === 'fiat' ? 'Settled · NGN' : 'Settled',
        className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300',
      }
    case 'settling':
      return { label: 'Settling to bank', className: 'bg-primary/10 text-primary' }
    case 'awaiting_claim':
      return {
        label: 'Awaiting claim',
        className: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
      }
    case 'pending':
      return {
        label: 'Pending',
        className: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
      }
    case 'expired':
      return { label: 'Expired', className: 'bg-foreground/10 text-foreground/70' }
    case 'failed':
      return {
        label: 'Failed',
        className: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300',
      }
  }
}

const CHANNELS = [
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'qr', label: 'QR' },
  { key: 'nfc', label: 'NFC' },
  { key: 'web', label: 'Web' },
]

function shortDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date)
}

function relativeTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Recently'
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return date.toLocaleDateString('en', { month: 'short', day: 'numeric' })
}

function DashboardSkeleton() {
  return (
    <div className="mx-auto max-w-6xl animate-pulse space-y-6" role="status" aria-label="Loading dashboard">
      <div className="h-8 w-44 rounded bg-primary/10" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => <div key={index} className="h-32 rounded-panel border border-primary/10 bg-surface" />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="h-80 rounded-panel border border-primary/10 bg-surface" />
        <div className="h-80 rounded-panel border border-primary/10 bg-surface" />
      </div>
      <div className="h-72 rounded-panel border border-primary/10 bg-surface" />
    </div>
  )
}

function DailyVolumeChart({ points }: { points: DashboardData['daily_volume'] }) {
  const width = 760
  const height = 230
  const pad = { top: 18, right: 12, bottom: 34, left: 12 }
  const chartWidth = width - pad.left - pad.right
  const chartHeight = height - pad.top - pad.bottom
  const values = points.map((point) => Number(point.amount_ngn) || 0)
  const max = Math.max(...values, 1)
  const coords = values.map((value, index) => ({
    x: pad.left + (points.length < 2 ? 0 : (index / (points.length - 1)) * chartWidth),
    y: pad.top + chartHeight - (value / max) * chartHeight,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
  const areaPath = `${path} L ${pad.left + chartWidth} ${pad.top + chartHeight} L ${pad.left} ${pad.top + chartHeight} Z`
  const hasVolume = values.some((value) => value > 0)

  return (
    <div className="relative">
      {!hasVolume && <p className="pointer-events-none absolute inset-x-0 top-1/2 z-10 -translate-y-1/2 text-center text-sm text-foreground/45">No payment volume in this period</p>}
      <svg viewBox={`0 0 ${width} ${height}`} className="h-56 w-full overflow-visible" role="img" aria-label="Daily payment volume in naira over the last 30 days">
        {[0, 0.5, 1].map((fraction) => {
          const y = pad.top + chartHeight * fraction
          return <line key={fraction} x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke="currentColor" className="text-primary/8" strokeDasharray="3 5" />
        })}
        {hasVolume && <path d={areaPath} fill="url(#volume-fill)" />}
        <path d={hasVolume ? path : `M ${pad.left} ${pad.top + chartHeight} L ${width - pad.right} ${pad.top + chartHeight}`} fill="none" stroke="currentColor" className="text-primary" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        <defs>
          <linearGradient id="volume-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 7, 14, 21, 29].filter((index) => points[index]).map((index) => (
          <text key={index} x={coords[index].x} y={height - 8} textAnchor={index === 0 ? 'start' : index === 29 ? 'end' : 'middle'} fill="currentColor" className="fill-foreground/45" fontSize="11">
            {shortDate(points[index].date)}
          </text>
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-foreground/40">
        <span>Peak {formatNgn(max)}</span><span>Daily volume · NGN</span>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reconcilingId, setReconcilingId] = useState<string | null>(null)
  const [reconcileError, setReconcileError] = useState<string | null>(null)

  const loadDashboard = useCallback(async () => {
    try {
      const result = await api<DashboardData>('/v1/dashboard')
      setData(result)
      setError(null)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDashboard()
  }, [loadDashboard])

  async function handleReconcileActivity(intentId: string) {
    setReconcilingId(intentId)
    setReconcileError(null)
    try {
      await reconcileIntent(intentId)
      await loadDashboard()
    } catch (err: unknown) {
      setReconcileError(err instanceof Error ? err.message : 'Could not reconcile payment status.')
    } finally {
      setReconcilingId(null)
    }
  }

  if (loading) return <DashboardSkeleton />
  if (!data) {
    return (
      <section className="mx-auto max-w-xl rounded-panel border border-primary/10 bg-surface p-8 text-center">
        <h1 className="text-xl font-semibold text-primary">Dashboard unavailable</h1>
        <p role="alert" className="mt-2 text-sm text-foreground/60">{error ?? 'Could not load dashboard data.'}</p>
        <Button className="mt-6" onClick={() => window.location.reload()}>Try again</Button>
      </section>
    )
  }

  const isEmpty = data.transactions_30d === 0 && data.recent_activity.length === 0 && Number(data.vault_locked_ngn) === 0
  const change = data.volume_change_percent === null ? null : Number(data.volume_change_percent)

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-primary">Dashboard</h1>
          <p className="mt-1 text-sm text-foreground/60">Your payment and payroll activity, in naira.</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" leftIcon={<Lightning size={16} weight="fill" />} onClick={() => navigate('/payments')}>New request</Button>
          <Button size="sm" variant="secondary" leftIcon={<PaperPlaneRight size={16} />} onClick={() => navigate('/payroll')}>Payroll</Button>
        </div>
      </header>

      <section aria-label="Key metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Volume · 30 days">
          <Money amountNgn={data.volume_30d_ngn} primaryClassName="text-2xl font-semibold tracking-tight text-primary" />
          <div className={`mt-2 text-xs font-medium ${change === null ? 'text-foreground/45' : change >= 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'}`}>
            {change === null ? 'No previous period volume' : `${change > 0 ? '+' : ''}${change.toFixed(1)}% vs previous 30 days`}
          </div>
        </KpiCard>
        <KpiCard label="Transactions · 30 days">
          <div className="font-mono text-2xl font-semibold tabular-nums text-primary">{data.transactions_30d.toLocaleString()}</div>
          <p className="mt-2 text-xs text-foreground/45">Average <Money amountNgn={data.avg_payment_ngn} primaryClassName="font-semibold" className="inline-flex" /></p>
        </KpiCard>
        <KpiCard label="Awaiting claim">
          <div className="font-mono text-2xl font-semibold tabular-nums text-primary">{data.awaiting_claim_count.toLocaleString()}</div>
          <Money amountNgn={data.awaiting_claim_ngn} className="mt-1" primaryClassName="text-xs font-medium text-foreground/60" />
        </KpiCard>
        <KpiCard label="Vault locked">
          <Money amountNgn={data.vault_locked_ngn} primaryClassName="text-2xl font-semibold tracking-tight text-primary" />
          <p className="mt-2 flex items-center gap-1.5 text-xs text-foreground/45"><LockKey size={13} /> Funded payroll vaults</p>
        </KpiCard>
      </section>

      {isEmpty ? (
        <section className="rounded-panel border border-primary/10 bg-surface px-6 py-12 text-center">
          <h2 className="text-xl font-semibold tracking-tight text-primary">Your dashboard is ready</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-foreground/55">Create a naira payment request or set up payroll to see your volume, channels, and activity here.</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button leftIcon={<ArrowDownLeft size={17} />} onClick={() => navigate('/payments')}>Request a payment</Button>
            <Button variant="secondary" leftIcon={<ArrowUpRight size={17} />} onClick={() => navigate('/payroll')}>Set up payroll</Button>
          </div>
        </section>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <section className="rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div><h2 className="font-semibold text-primary">Daily volume</h2><p className="mt-0.5 text-xs text-foreground/45">Last 30 days · all successful payments</p></div>
                <Money amountNgn={data.volume_30d_ngn} align="right" primaryClassName="text-sm font-semibold text-primary" />
              </div>
              <DailyVolumeChart points={data.daily_volume} />
            </section>

            <section className="rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
              <h2 className="font-semibold text-primary">By channel</h2>
              <p className="mt-0.5 text-xs text-foreground/45">All successful payments</p>
              <div className="mt-5 space-y-4">
                {CHANNELS.map((channel) => {
                  const item = data.by_channel[channel.key] ?? { total_ngn: '0', count: 0 }
                  const max = Math.max(...CHANNELS.map(({ key }) => Number(data.by_channel[key]?.total_ngn ?? 0)), 1)
                  const width = Math.max(0, Math.min(100, Number(item.total_ngn) / max * 100))
                  return (
                    <div key={channel.key}>
                      <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                        <span className="text-foreground/65">{channel.label}<span className="ml-1.5 text-xs text-foreground/35">{item.count}</span></span>
                        <Money amountNgn={item.total_ngn} align="right" primaryClassName="text-xs font-medium text-primary" />
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-pill bg-primary/5"><div className="h-full rounded-pill bg-primary/60" style={{ width: `${width}%` }} /></div>
                    </div>
                  )
                })}
              </div>
            </section>
          </div>

          <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
            <section className="rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
              <h2 className="font-semibold text-primary">Privacy split</h2>
              <p className="mt-0.5 text-xs text-foreground/45">All successful payments</p>
              <div className="mt-5 grid grid-cols-2 gap-3">
                {(['public', 'private'] as const).map((key) => (
                  <div key={key} className="rounded-card bg-background p-4">
                    <p className="text-xs font-medium capitalize text-foreground/50">{key}</p>
                    <Money amountNgn={data.by_privacy[key]?.total_ngn ?? '0'} className="mt-2" primaryClassName="text-lg font-semibold text-primary" />
                    <p className="mt-1 text-xs text-foreground/40">{data.by_privacy[key]?.count ?? 0} payments</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="overflow-hidden rounded-panel border border-primary/10 bg-surface">
              <div className="flex items-center justify-between gap-3 border-b border-primary/5 px-5 py-4">
                <div><h2 className="font-semibold text-primary">Recent activity</h2><p className="mt-0.5 text-xs text-foreground/45">Latest payment requests</p></div>
                <button type="button" onClick={() => navigate('/payments')} className="text-xs font-semibold text-primary hover:underline">Payments</button>
              </div>
              {reconcileError && (
                <p role="alert" className="border-b border-primary/5 bg-red-50 px-5 py-2.5 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-300">
                  {reconcileError}
                </p>
              )}
              {data.recent_activity.length === 0 ? <p className="px-5 py-9 text-center text-sm text-foreground/45">No recent activity yet.</p> : (
                <ul className="divide-y divide-primary/5">
                  {data.recent_activity.map((item) => {
                    const badge = getActivityStatusPresentation(item.settlement_status, item.settlement_target)
                    const railLabel = item.paid_via ? PAID_VIA_LABELS[item.paid_via] : null
                    const canReconcile =
                      item.settlement_status === 'pending' ||
                      item.settlement_status === 'settling' ||
                      item.settlement_status === 'awaiting_claim'
                    return (
                      <li key={item.id} className="flex items-center justify-between gap-4 px-5 py-3.5">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
                            <span className={`inline-flex rounded-pill px-2 py-0.5 text-[11px] font-medium ${badge.className}`}>
                              {badge.label}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-foreground/45">
                            <span className="capitalize">{item.channel}</span>
                            {railLabel ? ` · ${railLabel}` : ''} · {relativeTime(item.created_at)}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-3">
                          {canReconcile && (
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={reconcilingId === item.id}
                              onClick={() => void handleReconcileActivity(item.id)}
                            >
                              {reconcilingId === item.id ? 'Checking...' : 'Reconcile'}
                            </Button>
                          )}
                          <Money amountNgn={item.amount_ngn} tokenAmount={item.token_amount} token={item.token} align="right" primaryClassName="text-sm font-semibold text-primary" />
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}

function KpiCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <article className="min-h-32 rounded-panel border border-primary/10 bg-surface p-5">
      <p className="mb-3 text-xs font-medium text-foreground/50">{label}</p>
      {children}
    </article>
  )
}
