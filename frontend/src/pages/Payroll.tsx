import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Plus, UsersThree } from '@phosphor-icons/react'
import { PublicKey } from '@solana/web3.js'
import { Button } from '../components/ui/Button'
import { api } from '../services/api'

type Token = 'USDC' | 'SOL'

interface RecipientInput {
  name: string
  walletAddress: string
  amount: string
  memo: string
}

interface PayrollRecipient {
  id: string
  name: string
  walletAddress: string
  amountAtomic: string | null
  registrationStatus: string
}

interface PayrollGroup {
  id: string
  title: string
  token: Token
  status: string
  releaseAt: string
  totalAmountAtomic: string
  recipients: PayrollRecipient[]
}

const TOKEN_DECIMALS: Record<Token, number> = { USDC: 6, SOL: 9 }

function emptyRecipient(): RecipientInput {
  return { name: '', walletAddress: '', amount: '', memo: '' }
}

function defaultReleaseTime() {
  const date = new Date(Date.now() + 24 * 60 * 60 * 1000)
  date.setMinutes(0, 0, 0)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function toAtomicAmount(value: string, decimals: number): string | null {
  if (!/^\d+(?:\.\d*)?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  if (fraction.length > decimals) return null
  const atomic = BigInt(whole) * 10n ** BigInt(decimals) + BigInt(fraction.padEnd(decimals, '0') || '0')
  return atomic > 0n ? atomic.toString() : null
}

function displayAmount(amountAtomic: string, decimals: number) {
  const amount = BigInt(amountAtomic)
  const scale = 10n ** BigInt(decimals)
  const whole = (amount / scale).toLocaleString('en-US')
  const fraction = (amount % scale).toString().padStart(decimals, '0').replace(/0+$/, '')
  return `${whole}${fraction ? `.${fraction}` : ''}`
}

function formatRelease(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Release date unavailable'
    : date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

export default function Payroll() {
  const [groups, setGroups] = useState<PayrollGroup[]>([])
  const [title, setTitle] = useState('')
  const [token, setToken] = useState<Token>('USDC')
  const [releaseAt, setReleaseAt] = useState(defaultReleaseTime)
  const [recipients, setRecipients] = useState<RecipientInput[]>([emptyRecipient()])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const loadGroups = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setGroups(await api<PayrollGroup[]>('/v1/payroll/groups'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load payroll groups.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadGroups()
  }, [loadGroups])

  function updateRecipient(index: number, field: keyof RecipientInput, value: string) {
    setRecipients((current) =>
      current.map((recipient, currentIndex) =>
        currentIndex === index ? { ...recipient, [field]: value } : recipient,
      ),
    )
  }

  async function createPayroll(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSuccess(null)

    if (!title.trim()) {
      setError('Enter a name for this payroll group.')
      return
    }
    if (!releaseAt || Number.isNaN(new Date(releaseAt).getTime())) {
      setError('Choose a valid release date.')
      return
    }
    if (recipients.length === 0) {
      setError('Add at least one recipient.')
      return
    }

    const recipientPayload: { name: string; walletAddress: string; amountAtomic: string; memo?: string }[] = []
    for (const [index, recipient] of recipients.entries()) {
      if (!recipient.name.trim()) {
        setError(`Enter a name for recipient ${index + 1}.`)
        return
      }
      try {
        new PublicKey(recipient.walletAddress.trim())
      } catch {
        setError(`Enter a valid Solana wallet address for ${recipient.name.trim()}.`)
        return
      }
      const amountAtomic = toAtomicAmount(recipient.amount, TOKEN_DECIMALS[token])
      if (!amountAtomic) {
        setError(`Enter a positive ${token} amount for ${recipient.name.trim()} with up to ${TOKEN_DECIMALS[token]} decimal places.`)
        return
      }
      recipientPayload.push({
        name: recipient.name.trim(),
        walletAddress: recipient.walletAddress.trim(),
        amountAtomic,
        ...(recipient.memo.trim() ? { memo: recipient.memo.trim() } : {}),
      })
    }

    setSaving(true)
    try {
      const group = await api<PayrollGroup>('/v1/payroll/groups', {
        method: 'POST',
        body: JSON.stringify({
          employerRef: `PAY-${Date.now()}`,
          title: title.trim(),
          token,
          releaseAt: new Date(releaseAt).toISOString(),
          confirmationWindowHours: 2,
          autoProceedAfterConfirmationWindow: true,
          registrationLinkOpen: false,
          recipients: recipientPayload,
        }),
      })
      setGroups((current) => [group, ...current])
      setTitle('')
      setRecipients([emptyRecipient()])
      setSuccess(`“${group.title}” was created as a draft payroll group.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create this payroll group.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-primary">Payroll</h1>
        <p className="mt-1 text-sm text-foreground/70">
          Create a scheduled payroll group and track its recipients.
        </p>
      </header>

      {error && (
        <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      )}
      {success && (
        <p role="status" className="rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</p>
      )}

      <form onSubmit={(event) => void createPayroll(event)} className="space-y-5 rounded-panel border border-primary/10 bg-white p-5 shadow-veil-sm sm:p-6">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-card bg-primary/10 text-primary">
            <UsersThree size={21} weight="fill" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">New payroll group</h2>
            <p className="mt-0.5 text-sm text-foreground/60">Add recipient details and a planned release date.</p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="payroll-title" className="text-sm font-medium">Payroll name</label>
            <input
              id="payroll-title"
              required
              maxLength={120}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. November payroll"
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="payroll-release" className="text-sm font-medium">Planned release</label>
            <input
              id="payroll-release"
              required
              type="datetime-local"
              min={defaultReleaseTime()}
              value={releaseAt}
              onChange={(event) => setReleaseAt(event.target.value)}
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
          </div>
        </div>

        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Currency</legend>
          <div className="flex h-11 max-w-xs rounded-card bg-primary/5 p-1">
            {(['USDC', 'SOL'] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={token === option}
                onClick={() => setToken(option)}
                className={`flex-1 rounded-md text-sm font-medium transition-colors ${
                  token === option ? 'bg-white text-primary shadow-veil-sm' : 'text-foreground/60 hover:text-foreground'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">Recipients</h3>
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Plus size={16} weight="bold" />}
              onClick={() => setRecipients((current) => [...current, emptyRecipient()])}
            >
              Add recipient
            </Button>
          </div>

          {recipients.map((recipient, index) => (
            <fieldset key={index} className="grid gap-3 rounded-card border border-primary/10 bg-background/70 p-4 sm:grid-cols-2 lg:grid-cols-[1fr_1.5fr_0.8fr_1fr_auto]">
              <legend className="sr-only">Recipient {index + 1}</legend>
              <label className="space-y-1">
                <span className="text-xs font-medium text-foreground/65">Name</span>
                <input
                  required
                  value={recipient.name}
                  onChange={(event) => updateRecipient(index, 'name', event.target.value)}
                  placeholder="Employee name"
                  className="h-10 w-full rounded-card border border-primary/15 bg-white px-3 text-sm outline-none focus:border-primary/40"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-foreground/65">Solana wallet</span>
                <input
                  required
                  value={recipient.walletAddress}
                  onChange={(event) => updateRecipient(index, 'walletAddress', event.target.value)}
                  placeholder="Wallet address"
                  className="h-10 w-full rounded-card border border-primary/15 bg-white px-3 font-mono text-xs outline-none focus:border-primary/40"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-foreground/65">Amount ({token})</span>
                <input
                  required
                  type="number"
                  min="0"
                  step="any"
                  inputMode="decimal"
                  value={recipient.amount}
                  onChange={(event) => updateRecipient(index, 'amount', event.target.value)}
                  placeholder="0.00"
                  className="h-10 w-full rounded-card border border-primary/15 bg-white px-3 font-mono text-sm outline-none focus:border-primary/40"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-foreground/65">Note <span className="font-normal">(optional)</span></span>
                <input
                  value={recipient.memo}
                  onChange={(event) => updateRecipient(index, 'memo', event.target.value)}
                  placeholder="Reference"
                  className="h-10 w-full rounded-card border border-primary/15 bg-white px-3 text-sm outline-none focus:border-primary/40"
                />
              </label>
              <button
                type="button"
                aria-label={`Remove recipient ${index + 1}`}
                disabled={recipients.length === 1}
                onClick={() => setRecipients((current) => current.filter((_, currentIndex) => currentIndex !== index))}
                className="self-end rounded-card px-3 py-2 text-sm text-foreground/55 hover:bg-red-50 hover:text-red-700 focus-visible:outline-2 focus-visible:outline-accent disabled:invisible"
              >
                Remove
              </button>
            </fieldset>
          ))}
        </div>

        <div className="flex flex-col justify-between gap-4 border-t border-primary/10 pt-5 sm:flex-row sm:items-center">
          <p className="max-w-xl text-xs leading-relaxed text-foreground/55">
            This creates a draft group. Funding the vault and releasing payments on-chain are not available in this frontend yet.
          </p>
          <Button type="submit" size="lg" loading={saving} className="shrink-0">
            Create payroll group
          </Button>
        </div>
      </form>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-semibold tracking-tight">Your payroll groups</h2>
          <Button variant="secondary" size="sm" loading={loading} onClick={() => void loadGroups()}>
            Refresh
          </Button>
        </div>

        {loading && groups.length === 0 ? (
          <div className="flex min-h-32 items-center justify-center" role="status" aria-label="Loading payroll groups">
            <div className="size-7 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded-panel border border-dashed border-primary/20 bg-white/60 p-8 text-center">
            <p className="font-medium">No payroll groups yet</p>
            <p className="mt-1 text-sm text-foreground/60">Create a group above to get started.</p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {groups.map((group) => (
              <article key={group.id} className="rounded-panel border border-primary/10 bg-white p-5 shadow-veil-sm">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold">{group.title}</h3>
                    <p className="mt-1 text-sm text-foreground/60">{formatRelease(group.releaseAt)}</p>
                  </div>
                  <span className="shrink-0 rounded-pill bg-primary/5 px-3 py-1 text-xs font-medium capitalize text-primary">
                    {group.status}
                  </span>
                </div>
                <div className="mt-5 flex items-end justify-between border-t border-primary/5 pt-4">
                  <div>
                    <p className="text-xs text-foreground/55">Recipients</p>
                    <p className="mt-1 font-medium">{group.recipients.length}</p>
                  </div>
                  <p className="text-right font-semibold text-primary">
                    {displayAmount(group.totalAmountAtomic || '0', TOKEN_DECIMALS[group.token])} {group.token}
                  </p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
