import { useEffect, useState } from 'react'
import { ArrowUpRight, Lightning, LockKey, PaperPlaneRight, Wallet, CaretRight, Storefront, Money, ShoppingBag, MapPin } from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { useAuth } from '../auth/useAuth'

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

// --- Helpers ---
const formatDate = (isoStr: string | null) => {
  if (!isoStr) return 'N/A'
  const date = new Date(isoStr)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const getRelativeTime = (isoStr: string) => {
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const daysDifference = Math.round((new Date(isoStr).getTime() - new Date().getTime()) / (1000 * 60 * 60 * 24))
  return rtf.format(daysDifference, 'day')
}

const formatCurrency = (val: string) => {
  return parseFloat(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// --- Icon Picker based on Activity kind and source ---
const getActivityIcon = (item: ActivityItem) => {
  if (item.kind === 'payroll') return <Money weight="fill" className="text-amber-500" size={24} />
  if (item.source === 'whatsapp') return <Storefront weight="fill" className="text-emerald-500" size={24} />
  if (item.source === 'qr') return <ShoppingBag weight="fill" className="text-blue-500" size={24} />
  if (item.source === 'nfc') return <MapPin weight="fill" className="text-purple-500" size={24} />
  return <Wallet weight="fill" className="text-primary" size={24} />
}

export function Dashboard() {
  const { user } = useAuth()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  // Fetch data from FastAPI backend
  useEffect(() => {
    async function fetchDashboard() {
      if (!user) return
      try {
        const token = localStorage.getItem('veil_jwt') // Or wherever you store it
        const res = await fetch('http://localhost:8000/v1/dashboard', {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })
        if (res.ok) {
          const json = await res.json()
          setData(json)
        }
      } catch (err) {
        console.error("Failed to fetch dashboard", err)
      } finally {
        setLoading(false)
      }
    }
    fetchDashboard()
  }, [user])

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
        <div className="size-8 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-8 text-center text-foreground/60">
        <p>Could not load dashboard data. Please try again.</p>
      </div>
    )
  }

  const { stats, vault, recentActivity } = data

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 pb-12 sm:p-8">

      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Dashboard</h1>
        <p className="text-foreground/70">Overview of your payments and payroll.</p>
      </header>

      {/* --- QUICK STATS ROW --- */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Volume */}
        <div className="flex flex-col rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
          <span className="text-sm font-medium text-foreground/60">Volume (30d)</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight">{formatCurrency(stats.volume30d)}</span>
            <span className="text-sm font-semibold text-primary">{stats.currency}</span>
          </div>
        </div>

        {/* Transactions */}
        <div className="flex flex-col rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
          <span className="text-sm font-medium text-foreground/60">Transactions</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight">{stats.paymentCount30d}</span>
          </div>
          <span className="mt-1 text-sm text-foreground/50">≈${stats.avgPaymentAmount} avg</span>
        </div>

        {/* Awaiting Claim (Replaced Avg Fee Paid based on the contract) */}
        <div className="flex flex-col rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
          <span className="text-sm font-medium text-foreground/60">Awaiting Claim</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight">{formatCurrency(stats.awaitingClaim)}</span>
            <span className="text-sm font-semibold text-primary">{stats.currency}</span>
          </div>
          <span className="mt-1 text-sm text-foreground/50">Funded, pending withdrawal</span>
        </div>

        {/* Vault Locked */}
        <div className="flex flex-col rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-6 shadow-sm">
          <span className="text-sm font-medium text-emerald-700">Vault Locked</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight text-emerald-600">{formatCurrency(stats.vaultLocked)}</span>
            <span className="text-sm font-semibold text-emerald-600/70">{stats.currency}</span>
          </div>
          <span className="mt-1 flex items-center gap-1 text-sm text-emerald-600/80">
            <LockKey size={14} weight="bold" />
            Releasing {formatDate(stats.nextReleaseAt)}
          </span>
        </div>
      </section>

      {/* --- ACTIONS ROW --- */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Button size="lg" className="h-16 justify-start px-6 text-lg" leftIcon={<Lightning size={24} weight="fill" className="text-yellow-400" />}>
          <div className="flex flex-col items-start leading-tight">
            <span>Request Payment</span>
            <span className="text-xs font-normal opacity-80">Generate a private pay link or QR</span>
          </div>
        </Button>
        <Button variant="secondary" size="lg" className="h-16 justify-start px-6 text-lg" leftIcon={<PaperPlaneRight size={24} weight="fill" />}>
          <div className="flex flex-col items-start leading-tight">
            <span>Run Payroll</span>
            <span className="text-xs font-normal opacity-80">Schedule vault & pay team</span>
          </div>
        </Button>
      </section>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* --- MAIN COLUMN: RECENT ACTIVITY --- */}
        <section className="col-span-1 lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold tracking-tight">Recent Activity</h2>
            <button className="text-sm font-medium text-primary hover:underline">view all &rarr;</button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-primary/10 bg-white shadow-sm">
            {recentActivity.length === 0 ? (
               <div className="p-8 text-center text-sm text-foreground/50">No recent activity.</div>
            ) : (
              <ul className="divide-y divide-primary/5">
                {recentActivity.map((item) => (
                  <li key={item.id} className="flex items-center justify-between p-4 hover:bg-primary/[0.02] sm:p-5">
                    <div className="flex items-center gap-4">
                      <div className="flex size-10 flex-shrink-0 items-center justify-center rounded-full bg-primary/10">
                        {getActivityIcon(item)}
                      </div>
                      <div className="flex flex-col">
                        <span className="font-semibold">{item.title}</span>
                        <div className="flex items-center gap-2 text-sm text-foreground/60">
                          <span>{item.source || (item.kind === 'payroll' ? 'Vault release' : 'Web Link')}</span>
                          {item.isPrivate && (
                            <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-zinc-100">
                              Private
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-col items-end">
                      <span className={`font-semibold ${item.direction === 'in' ? 'text-emerald-600' : 'text-foreground'}`}>
                        {item.direction === 'in' ? '+' : '−'}{item.amount} {item.currency}
                      </span>
                      <span className="text-sm text-foreground/50">{getRelativeTime(item.occurredAt)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* --- SIDE COLUMN: VAULT STATUS --- */}
        <section className="col-span-1 space-y-4">
          <h2 className="text-xl font-semibold tracking-tight">Active Vault</h2>

          {vault ? (
             <div className="relative overflow-hidden rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 p-6 shadow-sm">
                <div className="absolute -right-4 -top-4 size-24 rounded-full bg-emerald-500/10 blur-2xl" />

                <h3 className="font-semibold text-emerald-900">{vault.title}</h3>

                <div className="mt-4 flex items-end justify-between">
                  <div className="flex flex-col">
                    <span className="text-2xl font-bold tracking-tight text-emerald-700">
                      {vault.total} <span className="text-lg">{vault.token}</span>
                    </span>
                  </div>
                </div>

                <div className="mt-6 flex flex-col gap-3">
                  <div className="flex items-center justify-between text-sm font-medium text-emerald-800/80">
                    <span className="flex items-center gap-1.5"><LockKey size={16} /> {vault.recipientCount} recipients</span>
                    <span>Funded</span>
                  </div>

                  <div className="h-2 w-full overflow-hidden rounded-full bg-emerald-500/20">
                    {/* Hardcoding 100% width since it's fully funded if it's in the vault */}
                    <div className="h-full w-full rounded-full bg-emerald-500" />
                  </div>

                  <p className="text-center text-xs font-medium text-emerald-700/70">
                    auto-release {getRelativeTime(vault.releaseAt)}
                  </p>
                </div>
             </div>
          ) : (
            <div className="flex h-48 flex-col items-center justify-center rounded-2xl border border-dashed border-primary/20 bg-white/50 text-center">
              <LockKey size={32} className="mb-2 text-foreground/30" />
              <p className="text-sm font-medium text-foreground/60">No active vault scheduled.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
