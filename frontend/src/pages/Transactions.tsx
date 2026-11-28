import { useCallback, useEffect, useState } from 'react'
import { Copy, PencilSimple, XCircle } from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { Money } from '../components/ui/Money'
import { api } from '../services/api'

type IntentStatus = 'created' | 'funded' | 'claimed' | 'failed'

interface Transaction {
  id: string
  amount_ngn: string
  amount_token?: string | null
  status: IntentStatus
  failureReason?: string | null
  memo: string | null
  settlementTarget?: 'crypto' | 'fiat'
  receiveMode: 'public' | 'private'
  createdAt: string
}

function statusLabel(transaction: Transaction) {
  if (transaction.failureReason === 'cancelled') return 'Cancelled'
  if (transaction.failureReason === 'expired') return 'Expired'
  if (transaction.status === 'created') return 'Awaiting payment'
  if (transaction.status === 'claimed' || transaction.status === 'funded') return 'Paid'
  return 'Failed'
}

function statusClass(transaction: Transaction) {
  return transaction.status === 'created'
    ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300'
    : transaction.failureReason === 'cancelled' || transaction.status === 'failed'
      ? 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300'
      : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300'
}

export default function Transactions() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [amount, setAmount] = useState('')
  const [memo, setMemo] = useState('')
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const loadTransactions = useCallback(async () => {
    try {
      setTransactions(await api<Transaction[]>('/v1/payments/intents'))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load transactions.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadTransactions() }, [loadTransactions])

  function openEdit(transaction: Transaction) {
    setEditing(transaction)
    setAmount(transaction.amount_ngn)
    setMemo(transaction.memo ?? '')
  }

  async function saveEdit() {
    if (!editing) return
    setSaving(true)
    setError(null)
    try {
      await api(`/v1/payments/intents/${editing.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ amountNgn: amount, memo }),
      })
      setEditing(null)
      await loadTransactions()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the payment request.')
    } finally {
      setSaving(false)
    }
  }

  async function cancel(transaction: Transaction) {
    if (!window.confirm('Cancel this unpaid payment link? Customers will no longer be able to pay it.')) return
    setBusyId(transaction.id)
    setError(null)
    try {
      await api(`/v1/payments/intents/${transaction.id}/cancel`, { method: 'POST' })
      await loadTransactions()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel the payment link.')
    } finally {
      setBusyId(null)
    }
  }

  async function copyLink(id: string) {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/pay/${id}`)
    } catch {
      setError('Could not copy the payment link.')
    }
  }

  return (
    <div className="w-full space-y-6 pb-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-primary">Transactions</h1>
          <p className="mt-1 text-sm text-foreground/60">Manage payment requests, links, and their settlement status.</p>
        </div>
        <Button onClick={() => { window.location.href = '/payments' }}>New payment request</Button>
      </header>

      {error && <p role="alert" className="rounded-card bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{error}</p>}
      {loading ? (
        <div className="rounded-panel border border-primary/10 bg-surface p-8 text-sm text-foreground/60">Loading transactions…</div>
      ) : transactions.length === 0 ? (
        <section className="rounded-panel border border-primary/10 bg-surface p-10 text-center">
          <h2 className="text-xl font-semibold text-primary">No payment requests yet</h2>
          <p className="mt-2 text-sm text-foreground/60">Create a request to see it here and manage the link later.</p>
        </section>
      ) : (
        <section className="overflow-hidden rounded-panel border border-primary/10 bg-surface">
          <div className="divide-y divide-primary/5">
            {transactions.map((transaction) => (
              <article key={transaction.id} className="flex flex-wrap items-center justify-between gap-4 p-5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate font-semibold text-primary">{transaction.memo || 'Payment request'}</h2>
                    <span className={`rounded-pill px-2.5 py-1 text-xs font-medium ${statusClass(transaction)}`}>{statusLabel(transaction)}</span>
                  </div>
                  <p className="mt-1 text-xs text-foreground/50">
                    {new Date(transaction.createdAt).toLocaleString()} · {transaction.settlementTarget === 'fiat' ? 'NGN settlement' : 'Crypto settlement'}
                  </p>
                  <Money amountNgn={transaction.amount_ngn} tokenAmount={transaction.amount_token} token="USDC" className="mt-2" primaryClassName="text-lg font-semibold text-primary" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" onClick={() => void copyLink(transaction.id)} leftIcon={<Copy size={15} />}>Copy link</Button>
                  {transaction.status === 'created' && (
                    <>
                      <Button size="sm" variant="secondary" onClick={() => openEdit(transaction)} leftIcon={<PencilSimple size={15} />}>Edit</Button>
                      <Button size="sm" variant="secondary" loading={busyId === transaction.id} onClick={() => void cancel(transaction)} leftIcon={<XCircle size={15} />}>Cancel</Button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {editing && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-primary/30 p-4" role="dialog" aria-modal="true" aria-labelledby="edit-payment-title">
          <form className="w-full max-w-md rounded-panel bg-surface p-6 shadow-veil-lg" onSubmit={(event) => { event.preventDefault(); void saveEdit() }}>
            <h2 id="edit-payment-title" className="text-xl font-semibold text-primary">Edit payment request</h2>
            <label className="mt-5 block text-sm font-medium text-primary">Amount in NGN<input className="mt-2 w-full rounded-card border border-primary/15 bg-background px-3 py-2" type="number" min="1" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label>
            <label className="mt-4 block text-sm font-medium text-primary">Memo<input className="mt-2 w-full rounded-card border border-primary/15 bg-background px-3 py-2" value={memo} onChange={(event) => setMemo(event.target.value)} placeholder="Payment request" /></label>
            <div className="mt-6 flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setEditing(null)}>Close</Button><Button type="submit" loading={saving}>Save changes</Button></div>
          </form>
        </div>
      )}
    </div>
  )
}
