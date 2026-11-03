import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  Lightning,
  LockKey,
  MapPin,
  Money,
  PaperPlaneRight,
  ShoppingBag,
  Storefront,
  Wallet,
} from '@phosphor-icons/react'
import { useNavigate } from 'react-router'
import { Button } from '../components/ui/Button'
import { api } from '../services/api'

interface Stats {
  currency: string
  volume30d: string
  paymentCount30d: number
  avgPaymentAmount: string
  awaitingClaim: string
  vaultLocked: string
  nextReleaseAt: string | null
}

interface ActivityItem {
  id: string
  kind: 'payment' | 'payroll'
  direction: 'in' | 'out'
  amount: string
  currency: string
  title: string
  status: string
  isPrivate: boolean
  source: string | null
  occurredAt: string
}

interface Vault {
  id: string
  title: string
  token: string
  status: 'locked' | 'scheduled'
  total: string
  recipientCount: number
  releaseAt: string
}

interface DashboardData {
  stats: Stats
  recentActivity: ActivityItem[]
  vault: Vault | null
}

function formatCurrency(value: string) {
  const amount = Number(value)
  return Number.isFinite(amount)
    ? amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—'
}

function formatDate(value: string | null) {
  if (!value) return 'No release scheduled'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'No release scheduled'
    : date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function relativeTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Recently'
  const days = Math.round((date.getTime() - Date.now()) / 86_400_000)
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(days, 'day')
}

function ActivityIcon({ item }: { item: ActivityItem }) {
  if (item.kind === 'payroll') return <Money weight="fill" size={20} />
  if (item.source === 'whatsapp') return <Storefront weight="fill" size={20} />
  if (item.source === 'qr') return <ShoppingBag weight="fill" size={20} />
  if (item.source === 'nfc') return <MapPin weight="fill" size={20} />
  return <Wallet weight="fill" size={20} />
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api<DashboardData>('/v1/dashboard'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDashboard()
  }, [loadDashboard])

  if (loading && !data) {
    return (
      <div className="flex min-h-64 items-center justify-center" role="status" aria-label="Loading dashboard">
        <div className="size-8 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
      </div>
    )
  }

  if (!data) {
    return (
      <section className="mx-auto max-w-xl rounded-panel border border-primary/10 bg-white p-8 text-center shadow-veil-sm">
        <h1 className="text-xl font-semibold text-primary">Dashboard unavailable</h1>
        <p role="alert" className="mt-2 text-sm text-foreground/60">
          {error ?? 'Could not load dashboard data.'}
        </p>
        <Button className="mt-6" loading={loading} onClick={() => void loadDashboard()}>
          Try again
        </Button>
      </section>
    )
  }

  const { stats, vault, recentActivity } = data

  return (
    <div className="mx-auto max-w-6xl space-y-8 pb-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight text-primary">Dashboard</h1>
        <p className="text-sm text-foreground/70">An overview of your payments and payroll.</p>
      </header>

      <section aria-label="Account overview" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Volume (30d)" value={formatCurrency(stats.volume30d)} unit={stats.currency} />
        <StatCard
          label="Payments (30d)"
          value={String(stats.paymentCount30d)}
          detail={`$${formatCurrency(stats.avgPaymentAmount)} average`}
        />
        <StatCard
          label="Awaiting claim"
          value={formatCurrency(stats.awaitingClaim)}
          unit={stats.currency}
          detail="Funded, pending withdrawal"
        />
        <StatCard
          label="Vault locked"
          value={formatCurrency(stats.vaultLocked)}
          unit={stats.currency}
          detail={
            <span className="flex items-center gap-1.5">
              <LockKey size={14} weight="bold" />
              Releases {formatDate(stats.nextReleaseAt)}
            </span>
          }
          highlight
        />
      </section>

      <section aria-label="Shortcuts" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Button
          size="lg"
          className="h-auto min-h-16 justify-start px-5 py-3 text-left"
          leftIcon={<Lightning size={22} weight="fill" />}
          onClick={() => navigate('/payments')}
        >
          <span className="flex flex-col items-start">
            <span>Request payment</span>
            <span className="text-xs font-normal opacity-75">Create a checkout link for a customer</span>
          </span>
        </Button>
        <Button
          variant="secondary"
          size="lg"
          className="h-auto min-h-16 justify-start px-5 py-3 text-left"
          leftIcon={<PaperPlaneRight size={22} weight="fill" />}
          onClick={() => navigate('/payroll')}
        >
          <span className="flex flex-col items-start">
            <span>Set up payroll</span>
            <span className="text-xs font-normal text-foreground/60">Create a recipient group and schedule</span>
          </span>
        </Button>
      </section>

      {error && (
        <p role="alert" className="rounded-card bg-red-50 px-4 py-3 text-sm text-red-700">
          Dashboard refresh failed: {error}
        </p>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <section className="space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold tracking-tight">Recent activity</h2>
            <button
              type="button"
              onClick={() => navigate('/payments')}
              className="text-sm font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              View payments
            </button>
          </div>
          <div className="overflow-hidden rounded-panel border border-primary/10 bg-white shadow-veil-sm">
            {recentActivity.length === 0 ? (
              <p className="p-8 text-center text-sm text-foreground/60">No recent activity yet.</p>
            ) : (
              <ul className="divide-y divide-primary/5">
                {recentActivity.map((item) => (
                  <li key={`${item.kind}-${item.id}`} className="flex items-center justify-between gap-4 p-4 sm:p-5">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary">
                        <ActivityIcon item={item} />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-medium">{item.title}</p>
                        <p className="mt-0.5 text-xs text-foreground/60">
                          {item.source || (item.kind === 'payroll' ? 'Payroll' : 'Payment link')}
                          {item.isPrivate && <span className="ml-2">· Private</span>}
                        </p>
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className={`font-semibold ${item.direction === 'in' ? 'text-emerald-700' : 'text-foreground'}`}>
                        {item.direction === 'in' ? '+' : '−'}{item.amount} {item.currency}
                      </p>
                      <p className="mt-0.5 text-xs text-foreground/50">{relativeTime(item.occurredAt)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-xl font-semibold tracking-tight">Active vault</h2>
          {vault ? (
            <article className="rounded-panel border border-emerald-500/20 bg-emerald-500/5 p-6">
              <p className="font-semibold text-emerald-950">{vault.title}</p>
              <p className="mt-4 text-2xl font-semibold tracking-tight text-emerald-800">
                {vault.total} <span className="text-base">{vault.token}</span>
              </p>
              <div className="mt-5 flex items-center justify-between text-sm text-emerald-900/75">
                <span className="flex items-center gap-1.5"><LockKey size={16} /> {vault.recipientCount} recipients</span>
                <span className="capitalize">{vault.status}</span>
              </div>
              <p className="mt-3 text-center text-xs text-emerald-800/70">
                Releases {relativeTime(vault.releaseAt)}
              </p>
            </article>
          ) : (
            <div className="flex min-h-40 flex-col items-center justify-center rounded-panel border border-dashed border-primary/20 bg-white/60 p-6 text-center">
              <LockKey size={28} className="mb-2 text-foreground/30" />
              <p className="text-sm font-medium text-foreground/60">No active vault scheduled.</p>
              <button
                type="button"
                onClick={() => navigate('/payroll')}
                className="mt-3 text-sm font-medium text-primary hover:underline"
              >
                Set up payroll
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  unit,
  detail,
  highlight = false,
}: {
  label: string
  value: string
  unit?: string
  detail?: ReactNode
  highlight?: boolean
}) {
  return (
    <article
      className={`rounded-panel border p-5 shadow-veil-sm ${
        highlight
          ? 'border-emerald-500/20 bg-emerald-500/5'
          : 'border-primary/10 bg-white'
      }`}
    >
      <p className="text-sm font-medium text-foreground/60">{label}</p>
      <p className={`mt-3 flex items-baseline gap-2 text-2xl font-semibold tracking-tight ${highlight ? 'text-emerald-800' : ''}`}>
        <span>{value}</span>
        {unit && <span className="text-sm font-medium text-foreground/50">{unit}</span>}
      </p>
      {detail && <div className="mt-2 text-xs text-foreground/55">{detail}</div>}
    </article>
  )
}
