import React, { useState, useRef, useMemo, useEffect } from 'react'
import Papa from 'papaparse'
import { PublicKey } from '@solana/web3.js'
import { useWallet } from '@solana/wallet-adapter-react'
import { WalletMultiButton } from '@solana/wallet-adapter-react-ui'
import {
  Users, CalendarBlank, UploadSimple, Plus,
  Trash, LockKey, CheckCircle, WarningCircle
} from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { api } from '../services/api'
import { fundPayrollVault } from '../lib/umbra'
import { Money } from '../components/ui/Money'

interface Rates { sol: string; usdc: string; asOf: string }

// --- Types ---
type PayoutToken = 'SOL'

interface Recipient {
  id: string
  name: string
  address: string
  amount: string
}

interface ParsedCsvRow {
  rowNumber: number
  name: string
  address: string
  amount: string
  errors: string[]
}

interface PendingLock {
  groupId: string
  vaultSignature: string
  quote: { rate: string; totalSol: string; recipients: Record<string, string> }
}

// --- Helpers ---
const isValidSolanaAddress = (address: string) => {
  try { new PublicKey(address); return true; } catch { return false; }
}

const normalizeAmount = (raw: string) => raw.trim().replace(/[\s,$₦£€¥]/g, '')

const isValidAmount = (amount: string) => {
  if (!/^\d*\.?\d+$/.test(amount)) return false
  if ((amount.split('.')[1] ?? '').length > 2) return false
  const num = parseFloat(amount)
  return Number.isFinite(num) && num > 0
}

const toScaledInteger = (value: string, decimals: number): bigint => {
  const [whole = '0', fraction = ''] = value.split('.')
  return BigInt(whole || '0') * 10n ** BigInt(decimals) + BigInt(fraction.padEnd(decimals, '0') || '0')
}

const ngnToLamports = (amountNgn: string, rateNgnPerSol: string): bigint => {
  const kobo = toScaledInteger(amountNgn, 2)
  const scaledRate = toScaledInteger(Number(rateNgnPerSol).toFixed(6), 6)
  const denominator = scaledRate
  return (kobo * 10_000_000_000_000n + denominator / 2n) / denominator
}

const lamportsToSol = (lamports: bigint): string => {
  const whole = lamports / 1_000_000_000n
  const fraction = (lamports % 1_000_000_000n).toString().padStart(9, '0').replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole.toString()
}

export default function Payroll() {
  const wallet = useWallet()
  const { publicKey } = wallet

  // Local State
  const [payrollDate, setPayrollDate] = useState('')
  const [payrollTime, setPayrollTime] = useState('')
  const payrollToken: PayoutToken = 'SOL'
  const [solRate, setSolRate] = useState<string | null>(null)
  const [rateError, setRateError] = useState(false)
  const [recipients, setRecipients] = useState<Recipient[]>([
    { id: crypto.randomUUID(), name: '', address: '', amount: '' }
  ])

  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [successGroupId, setSuccessGroupId] = useState<string | null>(null)
  const [pendingLock, setPendingLock] = useState<PendingLock | null>(null)
  const [lockedQuote, setLockedQuote] = useState<PendingLock['quote'] | null>(null)

  // CSV State
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [csvRows, setCsvRows] = useState<ParsedCsvRow[]>([])
  const [csvFileName, setCsvFileName] = useState<string | null>(null)

  // Derived State
  const total = useMemo(() => {
    return recipients.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0)
  }, [recipients])
  const csvValidCount = csvRows.filter(r => r.errors.length === 0).length

  useEffect(() => {
    let active = true
    const loadRate = async () => {
      try {
        const rates = await api<Rates>('/v1/rates')
        if (active) { setSolRate(rates.sol); setRateError(false) }
      } catch {
        if (active) setRateError(true)
      }
    }
    void loadRate()
    const interval = window.setInterval(() => void loadRate(), 60_000)
    return () => { active = false; window.clearInterval(interval) }
  }, [])

  const estimateSol = useMemo(() => {
    if (lockedQuote) return lockedQuote.totalSol
    if (!solRate) return null
    const lamports = recipients.reduce((sum, recipient) =>
      sum + (isValidAmount(recipient.amount) ? ngnToLamports(recipient.amount, solRate) : 0n), 0n)
    return lamportsToSol(lamports)
  }, [lockedQuote, recipients, solRate])

  // --- Recipient Management ---
  const addRecipient = () => {
    setRecipients(prev => [...prev, { id: crypto.randomUUID(), name: '', address: '', amount: '' }])
  }

  const updateRecipient = (id: string, field: keyof Recipient, value: string) => {
    setRecipients(prev => prev.map(r => r.id === id ? { ...r, [field]: value } : r))
  }

  const removeRecipient = (id: string) => {
    setRecipients(prev => prev.filter(r => r.id !== id))
  }

  // --- CSV Logic ---
  const handleCsvParse = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      transformHeader: h => h.trim().toLowerCase().replace(/[\s_-]+/g, ''),
      complete: (results) => {
        const fields = results.meta.fields ?? []
        const nameCol = fields.find(f => ['name', 'employee', 'fullname', 'employeename'].includes(f))
        const addressCol = fields.find(f => ['address', 'wallet', 'walletaddress', 'solanawalletaddress'].includes(f))
        const amountCol = fields.find(f => ['amount', 'salary', 'salaryamount', 'payamount'].includes(f))

        if (!nameCol || !addressCol || !amountCol) {
          setError('CSV must contain Name, Wallet, and Amount columns.')
          setCsvRows([])
          e.target.value = ''
          return
        }

        const parseError = results.errors[0]
        if (parseError) {
          const rowLabel = typeof parseError.row === 'number' ? parseError.row + 1 : 'unknown'
          setError(`Could not parse CSV row ${rowLabel}: ${parseError.message}`)
          setCsvRows([])
          e.target.value = ''
          return
        }

        const rows: ParsedCsvRow[] = results.data
          .filter(row => Object.values(row).some(v => (v ?? '').trim() !== ''))
          .map((row, index) => {
            const name = (row[nameCol] ?? '').trim()
            const address = (row[addressCol] ?? '').trim()
            const amount = normalizeAmount((row[amountCol] ?? '').trim())
            const errors: string[] = []

            if (!name) errors.push('Missing name')
            if (!address) errors.push('Missing address')
            else if (!isValidSolanaAddress(address)) errors.push('Invalid address')
            if (!amount) errors.push('Missing amount')
            else if (!isValidAmount(amount)) errors.push('Amount must be positive with at most 2 decimal places in NGN')

            return { rowNumber: index + 2, name, address, amount, errors }
          })

        if (rows.length === 0) {
          setError('The selected CSV does not contain any recipient rows.')
          setCsvRows([])
          e.target.value = ''
          return
        }

        setCsvRows(rows)
        setCsvFileName(file.name)
        e.target.value = ''
      }
    })
  }

  const handleImportCsv = () => {
    const validRows = csvRows.filter(r => r.errors.length === 0)
    const newRecipients = validRows.map(r => ({
      id: crypto.randomUUID(),
      name: r.name,
      address: r.address,
      amount: r.amount
    }))

    // Remove initial empty row if it's the only one
    if (recipients.length === 1 && !recipients[0].name && !recipients[0].address && !recipients[0].amount) {
      setRecipients(newRecipients)
    } else {
      setRecipients(prev => [...prev, ...newRecipients])
    }

    setCsvRows([])
    setCsvFileName(null)
  }

  // --- Submission ---
  const handleConfirm = async () => {
    setError(null)
    setStatusMessage(null)
    setSuccessGroupId(null)
    if (!publicKey) { setError('Please connect your wallet to fund payroll.'); return }
    if (!payrollDate || !payrollTime) { setError('Please set a release date and time.'); return }

    const filledRecipients = recipients.filter(r => r.name.trim() || r.address.trim() || parseFloat(r.amount) > 0)
    if (filledRecipients.length === 0) { setError('Add at least one recipient.'); return }

    const invalid = filledRecipients.find(r => !r.name.trim() || !isValidSolanaAddress(r.address) || !isValidAmount(r.amount.trim()))
    if (invalid) { setError('One or more recipients have invalid details.'); return }
    if (!solRate) { setError('The live SOL/NGN rate is unavailable. Try again shortly.'); return }

    const releaseAt = new Date(`${payrollDate}T${payrollTime}`)
    if (!Number.isFinite(releaseAt.getTime())) { setError('Please enter a valid release date and time.'); return }
    if (releaseAt.getTime() <= Date.now()) { setError('Release date and time must be in the future.'); return }
    const releaseAtIso = releaseAt.toISOString()

    setIsSubmitting(true)
    let vaultSignature: string | null = null
    let createdGroupId: string | null = null
    try {
      const formattedRecipients = filledRecipients.map(r => ({
        name: r.name.trim(),
        walletAddress: r.address.trim(),
        amountNgn: r.amount.trim(),
      }))
      const totalAtomic = filledRecipients.reduce((sum, r) => sum + ngnToLamports(r.amount.trim(), solRate), 0n)
      const quote = {
        rate: solRate,
        totalSol: lamportsToSol(totalAtomic),
        recipients: Object.fromEntries(filledRecipients.map((r) => [
          r.id,
          lamportsToSol(ngnToLamports(r.amount.trim(), solRate)),
        ])),
      }

      vaultSignature = await fundPayrollVault({
        wallet,
        token: payrollToken,
        totalAmountAtomic: totalAtomic,
        onStatus: setStatusMessage,
      })

      setStatusMessage('Saving payroll group...')
      const group = await api<{ id: string }>('/v1/payroll/groups', {
        method: 'POST',
        body: JSON.stringify({
          employerRef: `PAY-${Date.now()}`,
          title: `Payroll ${payrollDate}`,
          token: payrollToken,
          releaseAt: releaseAtIso,
          confirmationWindowHours: 2,
          autoProceedAfterConfirmationWindow: true,
          registrationLinkOpen: false,
          recipients: formattedRecipients,
        }),
      })
      createdGroupId = group.id
      setPendingLock({ groupId: group.id, vaultSignature, quote })

      setStatusMessage('Verifying transaction on-chain...')
      await api(`/v1/payroll/groups/${group.id}/lock`, {
        method: 'POST',
        body: JSON.stringify({ vaultSignature }),
      })
      setSuccessGroupId(group.id)
      setLockedQuote(quote)
      setPendingLock(null)
      setStatusMessage(null)
    } catch (err) {
      const reason = err instanceof Error ? err.message : 'Failed to fund payroll.'
      if (vaultSignature && createdGroupId) {
        setError(`Umbra deposit confirmed, but payroll group ${createdGroupId} could not be locked: ${reason}. Retry locking below; do not deposit again.`)
      } else if (vaultSignature) {
        setError(`Umbra deposit confirmed (${vaultSignature}), but the payroll group could not be saved: ${reason}. Funds remain in your Umbra vault; do not deposit again.`)
      } else {
        setError(reason)
      }
      setStatusMessage(null)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleRetryLock = async () => {
    if (!pendingLock) return
    setError(null)
    setStatusMessage('Checking payroll group status...')
    setIsSubmitting(true)
    try {
      const group = await api<{ status: string }>(`/v1/payroll/groups/${pendingLock.groupId}`)
      if (group.status !== 'locked') {
        setStatusMessage('Verifying transaction on-chain...')
        await api(`/v1/payroll/groups/${pendingLock.groupId}/lock`, {
          method: 'POST',
          body: JSON.stringify({ vaultSignature: pendingLock.vaultSignature }),
        })
      }
      setSuccessGroupId(pendingLock.groupId)
      setLockedQuote(pendingLock.quote)
      setPendingLock(null)
      setStatusMessage(null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not finish locking this payroll group.')
      setStatusMessage(null)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
      <div className="mx-auto max-w-6xl space-y-8 p-4 pb-12 sm:p-8">

        <header className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold tracking-tight text-primary">Run Payroll</h1>
          <p className="text-foreground/70">Schedule and fund multiple payments in a single transaction.</p>
        </header>

        {error && (
          <div className="flex items-center gap-3 rounded-card bg-red-50 p-4 text-red-700 dark:bg-red-950/45 dark:text-red-300">
            <WarningCircle className="shrink-0" size={24} weight="fill" />
            <span className="min-w-0 break-words text-sm font-medium">{error}</span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">

          {/* --- LEFT COLUMN (Config & Recipients) --- */}
          <div className="col-span-1 space-y-6 lg:col-span-2">

            {/* Settings Card */}
            <section className="rounded-2xl border border-primary/10 bg-surface p-6 shadow-sm">
              <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold tracking-tight text-primary">
                <CalendarBlank size={20} /> Schedule & Currency
              </h2>

              <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <label className="text-sm font-medium text-foreground/70">Payout currency</label>
                  <div className="flex h-10 items-center rounded-lg bg-primary/5 px-3 text-sm font-medium text-primary">
                    <span className="truncate">SOL (NGN)</span>
                  </div>
                  <span className="text-xs text-foreground/50">Enter amounts in NGN · SOL fixed on funding.</span>
                </div>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <label className="text-sm font-medium text-foreground/70">Release Date</label>
                  <input
                    type="date"
                    value={payrollDate}
                    onChange={(e) => setPayrollDate(e.target.value)}
                    className="h-10 w-full min-w-0 rounded-lg border border-primary/15 bg-transparent px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                  />
                </div>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <label className="text-sm font-medium text-foreground/70">Time (Local)</label>
                  <input
                    type="time"
                    value={payrollTime}
                    onChange={(e) => setPayrollTime(e.target.value)}
                    className="h-10 w-full min-w-0 rounded-lg border border-primary/15 bg-transparent px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                  />
                </div>
              </div>
            </section>

            {/* Recipients Card */}
            <section className="rounded-2xl border border-primary/10 bg-surface p-6 shadow-sm">
              <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-primary">
                  <Users size={20} /> Team Members
                </h2>

                <div className="flex gap-2">
                  <input ref={fileInputRef} type="file" accept=".csv" onChange={handleCsvParse} className="hidden" />
                  <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} leftIcon={<UploadSimple size={16} />}>
                    Import CSV
                  </Button>
                </div>
              </div>

              {/* CSV Preview */}
              {csvRows.length > 0 && (
                <div className="mb-6 overflow-hidden rounded-xl border border-emerald-500/20 bg-emerald-500/5">
                  <div className="flex min-w-0 flex-col gap-3 border-b border-emerald-500/10 p-3 sm:flex-row sm:items-center sm:justify-between sm:px-4">
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-semibold text-emerald-800 dark:text-emerald-300">{csvFileName}</span>
                      <span className="text-xs text-emerald-600/80 dark:text-emerald-300/75">{csvValidCount} ready · {csvRows.length - csvValidCount} with errors</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <button onClick={() => { setCsvRows([]); setCsvFileName(null) }} className="text-xs font-medium text-emerald-700 hover:underline dark:text-emerald-300">Cancel</button>
                      <Button size="sm" onClick={handleImportCsv} disabled={csvValidCount === 0} className="bg-emerald-600 hover:bg-emerald-700">
                        Import
                      </Button>
                    </div>
                  </div>
                  <div className="max-h-40 overflow-y-auto p-2">
                    {csvRows.map(row => (
                      <div key={row.rowNumber} title={row.errors.join(', ') || undefined} className="flex min-w-0 items-center gap-3 rounded-lg px-2 py-1 text-sm hover:bg-emerald-500/10">
                        {row.errors.length ? <WarningCircle className="text-red-500 dark:text-red-400" /> : <CheckCircle className="text-emerald-500 dark:text-emerald-400" />}
                        <span className="flex-1 truncate">{row.name || 'Unknown'}</span>
                        <Money amountNgn={row.amount || 0} tokenAmount={solRate && isValidAmount(row.amount) ? lamportsToSol(ngnToLamports(row.amount, solRate)) : null} token="SOL" align="right" primaryClassName="text-xs font-medium text-emerald-800 dark:text-emerald-300" />
                        {row.errors.length > 0 && <span className="max-w-32 truncate text-xs text-red-600 dark:text-red-400">{row.errors.join(', ')}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Manual Entry List */}
              <div className="space-y-3">
                {recipients.map((recipient, index) => {
                  const recipientSol = lockedQuote?.recipients[recipient.id]
                    ?? (solRate && isValidAmount(recipient.amount) ? lamportsToSol(ngnToLamports(recipient.amount, solRate)) : null)

                  return (
                    <div key={recipient.id} className="flex min-w-0 flex-col gap-1.5 rounded-xl bg-primary/[0.02] p-2">
                      <div className="flex min-w-0 flex-col gap-2 xl:flex-row xl:items-center">
                        <div className="hidden h-10 w-8 shrink-0 items-center justify-center font-mono text-xs font-semibold text-primary/40 xl:flex">
                          {index + 1}
                        </div>
                        <input
                          type="text"
                          placeholder="Full Name"
                          aria-label={`Recipient ${index + 1} name`}
                          value={recipient.name}
                          onChange={(e) => updateRecipient(recipient.id, 'name', e.target.value)}
                          className="h-10 w-full min-w-0 flex-1 rounded-lg border border-primary/10 bg-surface px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                        />
                        <input
                          type="text"
                          placeholder="Solana Wallet Address"
                          aria-label={`Recipient ${index + 1} Solana wallet address`}
                          value={recipient.address}
                          onChange={(e) => updateRecipient(recipient.id, 'address', e.target.value)}
                          className="h-10 w-full min-w-0 flex-[1.5] rounded-lg border border-primary/10 bg-surface px-3 text-sm font-mono focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                        />
                        <div className="flex min-w-0 items-center gap-2 xl:w-44 xl:shrink-0">
                          <input
                            type="text"
                            inputMode="decimal"
                            placeholder="Amount (₦)"
                            aria-label={`Recipient ${index + 1} amount in NGN`}
                            value={recipient.amount}
                            onChange={(e) => updateRecipient(recipient.id, 'amount', e.target.value)}
                            className="h-10 w-full min-w-0 flex-1 rounded-lg border border-primary/10 bg-surface px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                          />
                          <button
                            onClick={() => removeRecipient(recipient.id)}
                            aria-label={`Remove recipient ${index + 1}`}
                            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-foreground/40 transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                          >
                            <Trash size={18} />
                          </button>
                        </div>
                      </div>

                      {recipientSol && (
                        <div className="flex justify-end pr-12">
                          <Money
                            amountNgn={recipient.amount}
                            tokenAmount={recipientSol}
                            token="SOL"
                            align="right"
                            primaryClassName="text-xs text-foreground/60"
                          />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <Button variant="secondary" size="md" className="mt-4 border-dashed" fullWidth onClick={addRecipient} leftIcon={<Plus size={16} />}>
                Add another recipient
              </Button>

            </section>
          </div>

          {/* --- RIGHT COLUMN (Checkout / Summary) --- */}
          <div className="col-span-1">
            <div className="sticky top-24 space-y-4 rounded-2xl border border-primary/10 bg-surface p-6 shadow-sm">
              <h3 className="text-lg font-semibold tracking-tight text-primary">Summary</h3>

              <div className="flex flex-col gap-3 py-4 text-sm text-foreground/70">
                <div className="flex justify-between">
                  <span>Total Recipients</span>
                  <span className="font-medium text-foreground">{recipients.filter(r => r.name || r.amount).length}</span>
                </div>
                <div className="flex justify-between">
                  <span>Release Date</span>
                  <span className="font-medium text-foreground">{payrollDate ? payrollDate : 'Not set'}</span>
                </div>
                <div className="flex justify-between">
                  <span>Privacy</span>
                  <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-zinc-100">Private</span>
                </div>
              </div>

              <div className="border-t border-primary/10 pt-4">
                <div className="flex items-end justify-between">
                  <span className="text-sm font-medium text-foreground/70">Total Funding</span>
                  <div className="text-right">
                    <Money amountNgn={total} tokenAmount={estimateSol} token="SOL" align="right" primaryClassName="text-3xl font-bold tracking-tight text-primary" />
                  </div>
                </div>
                <p className="mt-2 text-right text-xs text-foreground/50">
                  {lockedQuote ? `Locked funding rate · ₦${Number(lockedQuote.rate).toLocaleString('en-NG')} per SOL` : solRate ? `Live rate · ₦${Number(solRate).toLocaleString('en-NG')} per SOL` : rateError ? 'Live rate unavailable' : 'Loading live rate…'}
                </p>
              </div>

              {!publicKey ? (
                <div className="mt-6 flex flex-col items-center gap-3">
                  <p className="text-sm font-medium text-red-500 dark:text-red-400">Wallet disconnected. Please reconnect to fund.</p>
                  <WalletMultiButton className="!bg-primary-action hover:!bg-primary-action-hover !h-14 !w-full !rounded-lg !flex !justify-center !text-base !font-semibold" />
                </div>
              ) : (
                <>
                  {statusMessage && <p className="mt-4 text-center text-sm text-foreground/70" role="status">{statusMessage}</p>}
                  {successGroupId && <p className="mt-4 text-center text-sm font-medium text-green-700 dark:text-emerald-300" role="status">Payroll group {successGroupId} funded and locked.</p>}
                  {pendingLock && <Button size="sm" fullWidth variant="secondary" disabled={isSubmitting} onClick={handleRetryLock}>Retry locking payroll group</Button>}
                  <Button
                    size="lg"
                    fullWidth
                    disabled={isSubmitting}
                    onClick={handleConfirm}
                    className="mt-6 h-14 whitespace-nowrap text-base shadow-lg shadow-primary/20"
                    leftIcon={<LockKey size={20} weight="bold" />}
                  >
                    {isSubmitting ? 'Processing…' : 'Schedule & Fund Payroll'}
                  </Button>
                </>
              )}

              <p className="mt-4 text-center text-xs leading-relaxed text-foreground/50">
                SOL deposits into your Umbra encrypted vault. Payroll group records are created here; automatic recipient payouts are not enabled yet.
              </p>
            </div>
          </div>

        </div>
      </div>
    )
}
