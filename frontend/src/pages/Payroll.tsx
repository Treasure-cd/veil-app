import React, { useState, useRef, useMemo } from 'react'
import Papa from 'papaparse'
import { PublicKey } from '@solana/web3.js'
import { useWallet } from '@solana/wallet-adapter-react'
import { WalletMultiButton } from '@solana/wallet-adapter-react-ui'
import {
  Users, CalendarBlank, UploadSimple, Plus,
  Trash, LockKey, CheckCircle, WarningCircle
} from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { loadSession } from '../auth/auth.storage'
// Import your umbra wrapper here when ready:
// import { umbra } from '../lib/umbra'

// --- Types ---
type PayoutToken = 'USDC' | 'SOL'

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

// --- Helpers ---
const isValidSolanaAddress = (address: string) => {
  try { new PublicKey(address); return true; } catch { return false; }
}

const normalizeAmount = (raw: string) => raw.replace(/[^\d.]/g, '')

const isValidAmount = (amount: string) => {
  if (!/^\d*\.?\d+$/.test(amount)) return false
  const num = parseFloat(amount)
  return Number.isFinite(num) && num > 0
}

export default function Payroll() {
  const { publicKey, signTransaction } = useWallet()

  // Local State
  const [payrollDate, setPayrollDate] = useState('')
  const [payrollTime, setPayrollTime] = useState('')
  const [payrollToken, setPayrollToken] = useState<PayoutToken>('USDC')
  const [recipients, setRecipients] = useState<Recipient[]>([
    { id: crypto.randomUUID(), name: '', address: '', amount: '' }
  ])

  const [isLocking, setIsLocking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // CSV State
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [csvRows, setCsvRows] = useState<ParsedCsvRow[]>([])
  const [csvFileName, setCsvFileName] = useState<string | null>(null)

  // Derived State
  const total = useMemo(() => {
    return recipients.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0)
  }, [recipients])
  const csvValidCount = csvRows.filter(r => r.errors.length === 0).length

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
      transformHeader: h => h.trim().toLowerCase(),
      complete: (results) => {
        const fields = results.meta.fields ?? []
        const nameCol = fields.find(f => ['name', 'employee'].includes(f))
        const addressCol = fields.find(f => ['address', 'wallet'].includes(f))
        const amountCol = fields.find(f => ['amount', 'salary'].includes(f))

        if (!nameCol || !addressCol || !amountCol) {
          setError('CSV must contain Name, Wallet, and Amount columns.')
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
            else if (!isValidAmount(amount)) errors.push('Invalid amount')

            return { rowNumber: index + 2, name, address, amount, errors }
          })

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
    if (recipients.length === 1 && !recipients[0].name && !recipients[0].address) {
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

    console.log('[Payroll Submission] Triggered check:', {
          publicKey: !!publicKey,
          signTransaction: !!signTransaction
        })
    if (!publicKey || !signTransaction) { setError('Please connect your wallet to fund payroll.'); return }
    if (!payrollDate || !payrollTime) { setError('Please set a release date and time.'); return }

    const filledRecipients = recipients.filter(r => r.name.trim() || r.address.trim() || parseFloat(r.amount) > 0)
    if (filledRecipients.length === 0) { setError('Add at least one recipient.'); return }

    const invalid = filledRecipients.find(r => !r.name.trim() || !isValidSolanaAddress(r.address) || !(parseFloat(r.amount) > 0))
    if (invalid) { setError('One or more recipients have invalid details.'); return }

    setIsLocking(true)
    try {
      const decimals = payrollToken === 'SOL' ? 9 : 6
      const session = loadSession()
      if (!session || !session.token) {
        throw new Error("Authentication session expired. Please log in again.")
      }
      const tokenStr = session.token

            // 1. Create Group
      const createRes = await fetch('http://localhost:8000/v1/payroll/groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${tokenStr}` },
        body: JSON.stringify({
          employerRef: `PAY-${Date.now()}`,
          title: `Payroll ${payrollDate}`,
          token: payrollToken,
          releaseAt: new Date(`${payrollDate}T${payrollTime}`).toISOString(),
          recipients: filledRecipients.map(r => ({
            name: r.name,
            walletAddress: r.address,
            amountAtomic: Math.round((parseFloat(r.amount) || 0) * 10 ** decimals).toString(),
          }))
        })
      })

      if (!createRes.ok) throw new Error("Failed to create payroll group.")
      const group = await createRes.json()

      // 2. Mock Solana Signature (Replace this block with umbra.lockPayrollVault when ready)
      console.log("Requesting signature from wallet...")
      // const signature = await umbra.lockPayrollVault(group, { publicKey, signTransaction })
      const signature = "mock_solana_signature_" + Date.now()

      // 3. Confirm Lock with Backend
      const lockRes = await fetch(`http://localhost:8000/v1/payroll/groups/${group.id}/lock`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${tokenStr}` },
              body: JSON.stringify({ vaultSignature: signature })
            })

            if (!lockRes.ok) {
              // Parse the error message from the backend
              const errorData = await lockRes.json().catch(() => null);
              console.error("Lock failure response:", errorData);
              throw new Error(errorData?.detail || "Failed to lock vault.");
            }

      // Success Reset
      setRecipients([{ id: crypto.randomUUID(), name: '', address: '', amount: '' }])
      setPayrollDate('')
      setPayrollTime('')
      alert("Payroll successfully scheduled and funded!")

    } catch (err: any) {
      setError(err.message || 'An error occurred during payroll submission.')

    } finally {
      setIsLocking(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 pb-12 sm:p-8">

      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Run Payroll</h1>
        <p className="text-foreground/70">Schedule and fund multiple payments in a single transaction.</p>
      </header>

      {error && (
        <div className="flex items-center gap-3 rounded-card bg-red-50 p-4 text-red-700">
          <WarningCircle size={24} weight="fill" />
          <span className="text-sm font-medium">{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">

        {/* --- LEFT COLUMN (Config & Recipients) --- */}
        <div className="col-span-1 space-y-6 lg:col-span-2">

          {/* Settings Card */}
          <section className="rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
            <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold tracking-tight text-primary">
              <CalendarBlank size={20} /> Schedule & Currency
            </h2>

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-foreground/70">Payout Token</label>
                <div className="flex h-10 items-center rounded-lg bg-primary/5 p-1">
                  {(['USDC', 'SOL'] as PayoutToken[]).map((t) => (
                    <button
                      key={t}
                      onClick={() => setPayrollToken(t)}
                      className={`flex-1 rounded-md text-sm font-medium transition-colors ${
                        payrollToken === t ? 'bg-white text-primary shadow-sm' : 'text-foreground/60 hover:text-foreground'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-foreground/70">Release Date</label>
                <input
                  type="date"
                  value={payrollDate}
                  onChange={(e) => setPayrollDate(e.target.value)}
                  className="h-10 rounded-lg border border-primary/15 bg-transparent px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-foreground/70">Time (Local)</label>
                <input
                  type="time"
                  value={payrollTime}
                  onChange={(e) => setPayrollTime(e.target.value)}
                  className="h-10 rounded-lg border border-primary/15 bg-transparent px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
              </div>
            </div>
          </section>

          {/* Recipients Card */}
          <section className="rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
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
                <div className="flex items-center justify-between border-b border-emerald-500/10 p-3 px-4">
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-emerald-800">{csvFileName}</span>
                    <span className="text-xs text-emerald-600/80">{csvValidCount} ready to import</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => { setCsvRows([]); setCsvFileName(null) }} className="text-xs font-medium text-emerald-700 hover:underline">Cancel</button>
                    <Button size="sm" onClick={handleImportCsv} disabled={csvValidCount === 0} className="bg-emerald-600 hover:bg-emerald-700">
                      Import
                    </Button>
                  </div>
                </div>
                <div className="max-h-40 overflow-y-auto p-2">
                  {csvRows.map(row => (
                    <div key={row.rowNumber} className="flex items-center gap-3 rounded-lg px-2 py-1 text-sm hover:bg-emerald-500/10">
                      {row.errors.length ? <WarningCircle className="text-red-500" /> : <CheckCircle className="text-emerald-500" />}
                      <span className="flex-1 truncate">{row.name || 'Unknown'}</span>
                      <span className="flex-1 text-right text-emerald-800 font-mono text-xs">{row.amount}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Manual Entry List */}
            <div className="space-y-3">
              {recipients.map((recipient, index) => (
                <div key={recipient.id} className="flex flex-col gap-2 rounded-xl bg-primary/[0.02] p-2 sm:flex-row sm:items-center">
                  <div className="hidden h-10 w-8 items-center justify-center font-mono text-xs font-semibold text-primary/40 sm:flex">
                    {index + 1}
                  </div>
                  <input
                    type="text"
                    placeholder="Full Name"
                    value={recipient.name}
                    onChange={(e) => updateRecipient(recipient.id, 'name', e.target.value)}
                    className="h-10 flex-1 rounded-lg border border-primary/10 bg-white px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                  />
                  <input
                    type="text"
                    placeholder="Solana Wallet Address"
                    value={recipient.address}
                    onChange={(e) => updateRecipient(recipient.id, 'address', e.target.value)}
                    className="h-10 flex-[1.5] rounded-lg border border-primary/10 bg-white px-3 text-sm font-mono focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                  />
                  <div className="flex flex-1 items-center gap-2">
                    <input
                      type="text"
                      placeholder="Amount"
                      value={recipient.amount}
                      onChange={(e) => updateRecipient(recipient.id, 'amount', e.target.value)}
                      className="h-10 flex-1 rounded-lg border border-primary/10 bg-white px-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                    <button
                      onClick={() => removeRecipient(recipient.id)}
                      className="flex h-10 w-10 items-center justify-center rounded-lg text-foreground/40 hover:bg-red-50 hover:text-red-500 transition-colors"
                    >
                      <Trash size={18} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <Button variant="secondary" size="md" className="mt-4 border-dashed" fullWidth onClick={addRecipient} leftIcon={<Plus size={16} />}>
              Add another recipient
            </Button>

          </section>
        </div>

        {/* --- RIGHT COLUMN (Checkout / Summary) --- */}
        <div className="col-span-1">
          <div className="sticky top-24 space-y-4 rounded-2xl border border-primary/10 bg-white p-6 shadow-sm">
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
                  <div className="text-3xl font-bold tracking-tight text-primary">{total.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
                  <div className="text-sm font-semibold text-primary/60">{payrollToken}</div>
                </div>
              </div>
            </div>

            {!publicKey ? (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-sm font-medium text-red-500">Wallet disconnected. Please reconnect to fund.</p>
                <WalletMultiButton className="!bg-primary hover:!bg-primary/90 !h-14 !w-full !rounded-lg !flex !justify-center !text-base !font-semibold" />
              </div>
            ) : (
              <Button
                size="lg"
                fullWidth
                onClick={handleConfirm}
                loading={isLocking}
                className="mt-6 h-14 text-base shadow-lg shadow-primary/20"
                leftIcon={<LockKey size={20} weight="bold" />}
              >
                Schedule & Fund Payroll
              </Button>
            )}

            <p className="mt-4 text-center text-xs leading-relaxed text-foreground/50">
              Funds will be securely locked in a smart contract vault and automatically disbursed at the scheduled time.
            </p>
          </div>
        </div>

      </div>
    </div>
  )
}
