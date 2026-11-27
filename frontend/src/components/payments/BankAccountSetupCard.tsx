import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bank, CheckCircle, Copy, MagnifyingGlass, Trash } from '@phosphor-icons/react'
import { Button } from '../ui/Button'
import { truncateAddress } from '../../lib/format'
import { IS_MAINNET } from '../../lib/network'
import {
  deleteMerchantBankAccount,
  listMerchantBankAccounts,
  listPajBanks,
  registerMerchantBankAccount,
  type MerchantBankAccount,
  type PajBank,
} from '../../services/paj'

interface BankAccountSetupCardProps {
  compact?: boolean
  onAccountChanged?: (accounts: MerchantBankAccount[]) => void
}

export function BankAccountSetupCard({
  compact = false,
  onAccountChanged,
}: BankAccountSetupCardProps) {
  const [accounts, setAccounts] = useState<MerchantBankAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [banks, setBanks] = useState<PajBank[]>([])
  const [banksLoading, setBanksLoading] = useState(true)
  const [bankQuery, setBankQuery] = useState('')
  const [bankCode, setBankCode] = useState('')
  const [accountNumber, setAccountNumber] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const onAccountChangedRef = useRef(onAccountChanged)
  onAccountChangedRef.current = onAccountChanged

  const loadData = useCallback(async () => {
    setAccountsLoading(true)
    setBanksLoading(true)
    setError(null)
    try {
      const [acctList, bankList] = await Promise.all([
        listMerchantBankAccounts(),
        listPajBanks(),
      ])
      setAccounts(acctList)
      setBanks(bankList)
      setShowForm(acctList.length === 0)
      onAccountChangedRef.current?.(acctList)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load Paj Cash bank settings.')
    } finally {
      setAccountsLoading(false)
      setBanksLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const filteredBanks = useMemo(() => {
    const q = bankQuery.trim().toLowerCase()
    if (!q) return banks
    return banks.filter(
      (b) => b.name.toLowerCase().includes(q) || b.code.toLowerCase().includes(q),
    )
  }, [banks, bankQuery])

  async function handleSave() {
    setError(null)
    if (!bankCode) {
      setError('Select a bank.')
      return
    }
    if (!/^\d{10}$/.test(accountNumber.trim())) {
      setError('Enter a 10-digit Nigerian bank account number.')
      return
    }
    setSubmitting(true)
    try {
      const created = await registerMerchantBankAccount(bankCode, accountNumber.trim(), true)
      const next = [
        created,
        ...accounts
          .filter((a) => a.id !== created.id)
          .map((a) => ({ ...a, isDefault: false })),
      ]
      setAccounts(next)
      setAccountNumber('')
      setBankCode('')
      setBankQuery('')
      setShowForm(false)
      onAccountChangedRef.current?.(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not verify and link this bank account.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(accountId: string) {
    setDeletingId(accountId)
    setError(null)
    try {
      await deleteMerchantBankAccount(accountId)
      const next = accounts.filter((a) => a.id !== accountId)
      setAccounts(next)
      if (next.length === 0) setShowForm(true)
      onAccountChangedRef.current?.(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove bank account.')
    } finally {
      setDeletingId(null)
    }
  }

  async function copySolanaAddress(address: string, id: string) {
    try {
      await navigator.clipboard.writeText(address)
      setCopiedId(id)
      window.setTimeout(() => setCopiedId((prev) => (prev === id ? null : prev)), 1800)
    } catch {
      // Clipboard may be unavailable.
    }
  }

  return (
    <section
      aria-labelledby="paj-bank-settings-title"
      className={compact
        ? 'rounded-card border border-primary/15 bg-background p-4 space-y-4'
        : 'rounded-panel border border-primary/10 bg-white p-5 sm:p-6 space-y-5'}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {!compact && (
            <span className="flex size-11 shrink-0 items-center justify-center rounded-card bg-primary/10 text-primary">
              <Bank size={24} weight="fill" aria-hidden="true" />
            </span>
          )}
          <div className="min-w-0">
            <h2 id="paj-bank-settings-title" className="text-sm font-semibold text-primary sm:text-base">
              Fiat settlement bank (Paj Cash)
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-foreground/60 sm:text-sm">
              Receive NGN directly in your Nigerian bank account regardless of which Solana token your customer sends.
            </p>
          </div>
        </div>
        {accounts.length > 0 && !showForm && (
          <Button size="sm" variant="secondary" onClick={() => setShowForm(true)}>
            Add / switch bank
          </Button>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">
          {error}
        </p>
      )}

      {accountsLoading ? (
        <div className="h-16 animate-pulse rounded-card bg-primary/5" role="status" aria-label="Loading linked bank accounts" />
      ) : accounts.length > 0 ? (
        <ul className="space-y-2.5">
          {accounts.map((acc) => (
            <li
              key={acc.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-primary/10 bg-white px-4 py-3"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">{acc.accountName}</span>
                  {acc.isDefault && (
                    <span className="inline-flex items-center gap-1 rounded-pill bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
                      <CheckCircle size={12} weight="fill" /> Default NGN payout
                    </span>
                  )}
                </div>
                <p className="text-xs text-foreground/65">
                  {acc.bankName} · <span className="font-mono tabular-nums">{acc.accountNumber}</span>
                </p>
                {acc.solanaAddress && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-foreground/55">
                    <span>{IS_MAINNET ? 'Auto-offramp address:' : 'Auto-offramp address (Mainnet):'}</span>
                    <span className="font-mono text-primary" title={acc.solanaAddress}>
                      {truncateAddress(acc.solanaAddress, 5)}
                    </span>
                    <button
                      type="button"
                      onClick={() => void copySolanaAddress(acc.solanaAddress as string, acc.id)}
                      className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-medium text-primary hover:bg-primary/5"
                    >
                      {copiedId === acc.id ? <CheckCircle size={12} weight="fill" /> : <Copy size={12} />}
                      {copiedId === acc.id ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                )}
              </div>
              <Button
                size="sm"
                variant="secondary"
                loading={deletingId === acc.id}
                leftIcon={<Trash size={14} />}
                onClick={() => void handleDelete(acc.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      {showForm && (
        <div className="space-y-3 rounded-card border border-primary/10 bg-white p-4">
          <div className="space-y-2">
            <label htmlFor="paj-bank-search" className="text-xs font-semibold text-foreground">
              Bank
            </label>
            <div className="relative">
              <MagnifyingGlass
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground/45"
                aria-hidden="true"
              />
              <input
                id="paj-bank-search"
                type="search"
                placeholder={banksLoading ? 'Loading banks…' : 'Search bank name or code'}
                value={bankQuery}
                onChange={(e) => setBankQuery(e.target.value)}
                className="h-11 w-full rounded-card border border-primary/15 bg-background pl-9 pr-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>
            <select
              aria-label="Select Paj bank"
              disabled={banksLoading}
              value={bankCode}
              onChange={(e) => setBankCode(e.target.value)}
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10 disabled:opacity-60"
            >
              <option value="">
                {banksLoading ? 'Loading banks…' : `Select a bank (${filteredBanks.length})`}
              </option>
              {filteredBanks.map((bank, idx) => (
                <option key={`${bank.code}-${idx}`} value={bank.code}>
                  {bank.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="paj-account-number" className="text-xs font-semibold text-foreground">
              Account number
            </label>
            <input
              id="paj-account-number"
              type="text"
              inputMode="numeric"
              maxLength={10}
              placeholder="0123456789"
              value={accountNumber}
              onChange={(e) => setAccountNumber(e.target.value.replace(/\D/g, '').slice(0, 10))}
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm tabular-nums outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="md" loading={submitting} onClick={() => void handleSave()}>
              Verify & link bank account
            </Button>
            {accounts.length > 0 && (
              <Button size="md" variant="secondary" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
