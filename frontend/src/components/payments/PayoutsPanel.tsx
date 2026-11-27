import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowsClockwise,
  Bank,
  CheckCircle,
  MagnifyingGlass,
  PaperPlaneRight,
  XCircle,
} from '@phosphor-icons/react'
import { Button } from '../ui/Button'
import { truncateAddress } from '../../lib/format'
import { formatNgn } from '../../lib/money'
import { solanaExplorerTxUrl } from '../../lib/network'
import {
  createFiatPayout,
  expireFiatPayment,
  getFiatStatusPresentation,
  getFiatTransferFee,
  listFiatBanks,
  listFiatPayments,
  reconcileFiatPayment,
  verifyBankAccount,
  type BankNameEnquiryResult,
  type FiatFeeQuote,
  type FiatPayment,
  type FiatPaymentFlow,
  type SupportedBank,
} from '../../services/fiat'
import {
  getPajStatusPresentation,
  listPajOfframps,
  reconcilePajOfframp,
  type PajOfframpOrder,
} from '../../services/paj'

function formatTimestamp(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-NG', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function PayoutsPanel() {
  const [banks, setBanks] = useState<SupportedBank[]>([])
  const [banksLoading, setBanksLoading] = useState(true)
  const [banksError, setBanksError] = useState<string | null>(null)
  const [bankQuery, setBankQuery] = useState('')
  const [bankCode, setBankCode] = useState('')

  const [accountNumber, setAccountNumber] = useState('')
  const [enquiry, setEnquiry] = useState<BankNameEnquiryResult | null>(null)
  const [verifyingAccount, setVerifyingAccount] = useState(false)
  const [enquiryError, setEnquiryError] = useState<string | null>(null)

  const [amount, setAmount] = useState('')
  const [remarks, setRemarks] = useState('')
  const [feeQuote, setFeeQuote] = useState<FiatFeeQuote | null>(null)
  const [feeLoading, setFeeLoading] = useState(false)
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<FiatPayment | null>(null)

  const [history, setHistory] = useState<FiatPayment[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [flowFilter, setFlowFilter] = useState<'all' | FiatPaymentFlow>('all')
  const [busyRowId, setBusyRowId] = useState<string | null>(null)

  const [activitySource, setActivitySource] = useState<'fossapay' | 'paj'>('fossapay')
  const [pajOrders, setPajOrders] = useState<PajOfframpOrder[]>([])
  const [pajLoading, setPajLoading] = useState(true)
  const [pajError, setPajError] = useState<string | null>(null)
  const [busyPajId, setBusyPajId] = useState<string | null>(null)

  const loadBanks = useCallback(async () => {
    setBanksLoading(true)
    setBanksError(null)
    try {
      const data = await listFiatBanks()
      setBanks(data)
    } catch (err) {
      setBanksError(err instanceof Error ? err.message : 'Could not load supported banks.')
    } finally {
      setBanksLoading(false)
    }
  }, [])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const data = await listFiatPayments()
      setHistory(data)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Could not load fiat transactions.')
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const loadPajOrders = useCallback(async () => {
    setPajLoading(true)
    setPajError(null)
    try {
      const data = await listPajOfframps()
      setPajOrders(data)
    } catch (err) {
      setPajError(err instanceof Error ? err.message : 'Could not load Paj Cash offramp orders.')
    } finally {
      setPajLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadBanks()
    void loadHistory()
    void loadPajOrders()
  }, [loadBanks, loadHistory, loadPajOrders])

  const filteredBanks = useMemo(() => {
    const query = bankQuery.trim().toLowerCase()
    if (!query) return banks
    return banks.filter(
      (bank) =>
        bank.bankname.toLowerCase().includes(query) ||
        bank.bankcode.toLowerCase().includes(query),
    )
  }, [banks, bankQuery])

  const selectedBank = useMemo(
    () => banks.find((bank) => bank.bankcode === bankCode) ?? null,
    [banks, bankCode],
  )

  useEffect(() => {
    setEnquiry(null)
    setEnquiryError(null)
    if (!bankCode || !/^\d{10}$/.test(accountNumber.trim())) return

    let active = true
    setVerifyingAccount(true)
    void verifyBankAccount(bankCode, accountNumber.trim())
      .then((result) => {
        if (active) {
          setEnquiry(result)
          setEnquiryError(null)
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setEnquiry(null)
          setEnquiryError(err instanceof Error ? err.message : 'Could not verify this bank account.')
        }
      })
      .finally(() => {
        if (active) setVerifyingAccount(false)
      })
    return () => {
      active = false
    }
  }, [bankCode, accountNumber])

  const validIntegerAmount = useMemo(() => {
    if (!/^\d+$/.test(amount.trim())) return null
    const parsed = Number(amount.trim())
    return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : null
  }, [amount])

  useEffect(() => {
    setFeeQuote(null)
    if (validIntegerAmount === null) return

    let active = true
    setFeeLoading(true)
    const timer = window.setTimeout(() => {
      void getFiatTransferFee(validIntegerAmount)
        .then((quote) => {
          if (active) setFeeQuote(quote)
        })
        .catch(() => {
          if (active) setFeeQuote(null)
        })
        .finally(() => {
          if (active) setFeeLoading(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [validIntegerAmount])

  function resetDraftIdempotency() {
    setIdempotencyKey(crypto.randomUUID())
  }

  async function handlePayout() {
    setSubmitError(null)
    setSubmitSuccess(null)
    if (!selectedBank) {
      setSubmitError('Select a destination Nigerian bank.')
      return
    }
    if (!enquiry?.accountName) {
      setSubmitError('Verify a valid 10-digit account number before sending a payout.')
      return
    }
    if (validIntegerAmount === null) {
      setSubmitError('Enter a whole-naira payout amount of at least ₦1.')
      return
    }

    setSubmitting(true)
    try {
      const created = await createFiatPayout({
        amountNgn: validIntegerAmount,
        bankCode: selectedBank.bankcode,
        bankName: selectedBank.bankname,
        accountNumber: accountNumber.trim(),
        accountName: enquiry.accountName,
        remarks: remarks.trim() || undefined,
        idempotencyKey,
      })
      setSubmitSuccess(created)
      setHistory((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      setAmount('')
      setRemarks('')
      setIdempotencyKey(crypto.randomUUID())
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Could not submit the NGN payout.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReconcile(payment: FiatPayment) {
    setBusyRowId(payment.id)
    setHistoryError(null)
    try {
      const updated = await reconcileFiatPayment(payment.id)
      setHistory((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Could not refresh payment status.')
    } finally {
      setBusyRowId(null)
    }
  }

  async function handleReconcilePaj(order: PajOfframpOrder) {
    setBusyPajId(order.id)
    setPajError(null)
    try {
      const updated = await reconcilePajOfframp(order.id)
      setPajOrders((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err) {
      setPajError(err instanceof Error ? err.message : 'Could not reconcile Paj offramp status.')
    } finally {
      setBusyPajId(null)
    }
  }

  async function handleExpire(payment: FiatPayment) {
    setBusyRowId(payment.id)
    setHistoryError(null)
    try {
      const updated = await expireFiatPayment(payment.id)
      setHistory((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not expire checkout.'
      if (/only a pending checkout can be expired|current status is/i.test(message)) {
        try {
          const synced = await reconcileFiatPayment(payment.id)
          setHistory((prev) => prev.map((item) => (item.id === synced.id ? synced : item)))
          if (synced.status === 'expired') return
        } catch {
          // Fall back to reporting the expire error and reloading list.
        }
      }
      setHistoryError(message)
      void loadHistory()
    } finally {
      setBusyRowId(null)
    }
  }

  const visibleHistory = useMemo(() => {
    if (flowFilter === 'all') return history
    return history.filter((item) => item.flow === flowFilter)
  }, [history, flowFilter])

  const canSubmit = Boolean(selectedBank && enquiry?.accountName && validIntegerAmount !== null && !verifyingAccount)

  return (
    <div className="space-y-6">
      {submitError && (
        <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
          {submitError}
        </p>
      )}
      {submitSuccess && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950/45 dark:text-emerald-300">
          <p className="flex items-center gap-2 font-medium">
            <CheckCircle size={18} weight="fill" className="shrink-0" />
            Payout of {formatNgn(submitSuccess.amount)} to {submitSuccess.accountName} submitted ({submitSuccess.status}).
          </p>
          <span className="font-mono text-xs text-emerald-900/75 dark:text-emerald-300/80">{submitSuccess.reference}</span>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="space-y-5 rounded-panel border border-primary/10 bg-surface p-5 shadow-veil-sm sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-primary">Send NGN to bank account</h2>
              <p className="mt-0.5 text-xs text-foreground/55">
                Verify the beneficiary account name via FossaPay before initiating a payout.
              </p>
            </div>
            <Bank size={22} weight="duotone" className="shrink-0 text-primary/70" aria-hidden="true" />
          </div>

          <div className="space-y-2">
            <label htmlFor="bank-search" className="text-sm font-medium">Destination bank</label>
            {banksError ? (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
                <span>{banksError}</span>
                <button type="button" onClick={() => void loadBanks()} className="font-medium underline">
                  Retry
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="relative">
                  <MagnifyingGlass
                    size={16}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground/45"
                    aria-hidden="true"
                  />
                  <input
                    id="bank-search"
                    type="search"
                    placeholder={banksLoading ? 'Loading Nigerian banks…' : 'Search bank name or code'}
                    value={bankQuery}
                    onChange={(event) => setBankQuery(event.target.value)}
                    className="h-11 w-full rounded-card border border-primary/15 bg-background pl-9 pr-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                  />
                </div>
                <select
                  aria-label="Select bank"
                  disabled={banksLoading}
                  value={bankCode}
                  onChange={(event) => {
                    setBankCode(event.target.value)
                    resetDraftIdempotency()
                  }}
                  className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10 disabled:opacity-60"
                >
                  <option value="">
                    {banksLoading ? 'Loading banks…' : `Select a bank (${filteredBanks.length})`}
                  </option>
                  {filteredBanks.map((bank, index) => (
                    <option key={`${bank.bankcode}-${index}`} value={bank.bankcode}>
                      {bank.bankname}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="payout-account-number" className="text-sm font-medium">Account number</label>
              <input
                id="payout-account-number"
                type="text"
                inputMode="numeric"
                maxLength={10}
                placeholder="0123456789"
                value={accountNumber}
                onChange={(event) => {
                  const digits = event.target.value.replace(/\D/g, '').slice(0, 10)
                  setAccountNumber(digits)
                  resetDraftIdempotency()
                }}
                className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm tabular-nums outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="payout-amount" className="text-sm font-medium">Amount (NGN)</label>
              <input
                id="payout-amount"
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                placeholder="5000"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value)
                  resetDraftIdempotency()
                }}
                className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm tabular-nums outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>
          </div>

          {verifyingAccount && (
            <p role="status" className="text-xs text-foreground/60">
              Verifying account name…
            </p>
          )}
          {enquiry && (
            <div className="flex items-center gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-sm text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950/45 dark:text-emerald-300">
              <CheckCircle size={18} weight="fill" className="shrink-0" />
              <span className="font-medium">{enquiry.accountName}</span>
            </div>
          )}
          {enquiryError && (
            <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
              {enquiryError}
            </p>
          )}

          <div className="space-y-1.5">
            <label htmlFor="payout-remarks" className="text-sm font-medium">Remarks (optional)</label>
            <input
              id="payout-remarks"
              type="text"
              maxLength={255}
              placeholder="e.g. Vendor settlement"
              value={remarks}
              onChange={(event) => {
                setRemarks(event.target.value)
                resetDraftIdempotency()
              }}
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
          </div>
        </section>

        <aside className="flex flex-col rounded-panel border border-primary/10 bg-primary/[0.035] p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-primary">Payout summary</h2>
          <dl className="my-6 flex-1 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-foreground/60">Beneficiary</dt>
              <dd className="truncate font-medium text-foreground">
                {enquiry?.accountName ?? 'Unverified'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-foreground/60">Bank</dt>
              <dd className="truncate font-medium text-foreground">
                {selectedBank?.bankname ?? '—'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-foreground/60">Account</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {accountNumber || '—'}
              </dd>
            </div>
            <div className="border-t border-primary/10 pt-3 flex items-center justify-between gap-3">
              <dt className="text-foreground/60">Amount</dt>
              <dd className="font-mono font-semibold tabular-nums text-primary">
                {validIntegerAmount !== null ? formatNgn(validIntegerAmount) : '₦—'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-foreground/60">Transfer fee</dt>
              <dd className="font-mono tabular-nums text-foreground/75">
                {feeLoading ? 'Calculating…' : feeQuote ? formatNgn(feeQuote.feeAmount) : '—'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-primary/10 pt-3">
              <dt className="font-medium text-foreground">Total debited</dt>
              <dd className="font-mono text-lg font-semibold tabular-nums text-primary">
                {feeQuote
                  ? formatNgn(feeQuote.total)
                  : validIntegerAmount !== null
                    ? formatNgn(validIntegerAmount)
                    : '₦—'}
              </dd>
            </div>
          </dl>

          <Button
            size="lg"
            fullWidth
            loading={submitting}
            disabled={!canSubmit}
            leftIcon={<PaperPlaneRight size={18} weight="bold" />}
            onClick={() => void handlePayout()}
          >
            Send NGN payout
          </Button>
          <p className="mt-3 text-center text-xs text-foreground/55">
            Protected by per-transfer idempotency keys.
          </p>
        </aside>
      </div>

      <section className="overflow-hidden rounded-panel border border-primary/10 bg-surface shadow-veil-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-primary/10 px-5 py-4">
          <div>
            <h2 className="font-semibold text-primary">Fiat activity</h2>
            <p className="mt-0.5 text-xs text-foreground/50">
              {activitySource === 'fossapay'
                ? 'NGN bank-transfer checkouts and master-wallet payouts'
                : 'Multi-token Solana crypto-to-NGN offramp settlements via Paj Cash'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-pill border border-primary/10 bg-background p-0.5" role="tablist" aria-label="Fiat activity source">
              <button
                type="button"
                role="tab"
                aria-selected={activitySource === 'fossapay'}
                onClick={() => setActivitySource('fossapay')}
                className={`min-h-8 rounded-pill px-3 text-xs font-semibold transition-colors ${
                  activitySource === 'fossapay' ? 'bg-primary-action text-white' : 'text-foreground/60 hover:text-primary'
                }`}
              >
                FossaPay
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activitySource === 'paj'}
                onClick={() => setActivitySource('paj')}
                className={`min-h-8 rounded-pill px-3 text-xs font-semibold transition-colors ${
                  activitySource === 'paj' ? 'bg-primary-action text-white' : 'text-foreground/60 hover:text-primary'
                }`}
              >
                Paj Offramps
              </button>
            </div>
            {activitySource === 'fossapay' && (
              <div className="inline-flex rounded-pill border border-primary/10 bg-background p-0.5" role="group" aria-label="Filter fiat activity">
                {(['all', 'checkout', 'payout'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    aria-pressed={flowFilter === tab}
                    onClick={() => setFlowFilter(tab)}
                    className={`min-h-8 rounded-pill px-3 text-xs font-semibold capitalize transition-colors ${
                      flowFilter === tab ? 'bg-primary-action text-white' : 'text-foreground/60 hover:text-primary'
                    }`}
                  >
                    {tab === 'all' ? 'All' : `${tab}s`}
                  </button>
                ))}
              </div>
            )}
            <Button
              size="sm"
              variant="secondary"
              loading={activitySource === 'fossapay' ? historyLoading : pajLoading}
              leftIcon={<ArrowsClockwise size={15} />}
              onClick={() => void (activitySource === 'fossapay' ? loadHistory() : loadPajOrders())}
            >
              Refresh
            </Button>
          </div>
        </div>

        {activitySource === 'paj' ? (
          <>
            {pajError && (
              <p role="alert" className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
                {pajError}
              </p>
            )}

            {pajLoading ? (
              <div className="space-y-3 p-5" role="status" aria-label="Loading Paj offramp orders">
                {Array.from({ length: 3 }, (_, idx) => (
                  <div key={idx} className="h-14 animate-pulse rounded-card bg-primary/5" />
                ))}
              </div>
            ) : pajOrders.length === 0 ? (
              <p className="px-5 py-10 text-center text-sm text-foreground/50">
                No Paj Cash multi-token offramp orders recorded yet.
              </p>
            ) : (
              <>
                <div className="hidden overflow-x-auto md:block">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-primary/10 bg-background text-xs font-medium text-foreground/55">
                      <tr>
                        <th className="px-5 py-3">Token</th>
                        <th className="px-5 py-3">Deposit address</th>
                        <th className="px-5 py-3">Bank destination</th>
                        <th className="px-5 py-3">NGN amount</th>
                        <th className="px-5 py-3">Status</th>
                        <th className="px-5 py-3">Created</th>
                        <th className="px-5 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-primary/5">
                      {pajOrders.map((order) => {
                        const badge = getPajStatusPresentation(order.status)
                        const busy = busyPajId === order.id
                        return (
                          <tr key={order.id} className="hover:bg-primary/[0.02]">
                            <td className="px-5 py-3.5 font-mono tabular-nums">
                              <p className="font-semibold text-primary">
                                {order.tokenAmount ? `${order.tokenAmount} ` : ''}
                                {order.tokenSymbol}
                              </p>
                              {order.txSignature && (
                                <a
                                  href={solanaExplorerTxUrl(order.txSignature)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-xs text-primary/70 underline underline-offset-2"
                                >
                                  tx {truncateAddress(order.txSignature, 4)}
                                </a>
                              )}
                            </td>
                            <td className="px-5 py-3.5 font-mono text-xs text-foreground/75" title={order.depositAddress}>
                              {truncateAddress(order.depositAddress, 5)}
                            </td>
                            <td className="px-5 py-3.5 text-xs">
                              <p className="font-medium text-foreground">{order.bankName || '—'}</p>
                              <p className="font-mono tabular-nums text-foreground/60">
                                {order.accountNumber || '—'} {order.accountName ? `· ${order.accountName}` : ''}
                              </p>
                            </td>
                            <td className="px-5 py-3.5 font-mono tabular-nums">
                              <p className="font-semibold text-primary">{formatNgn(order.fiatAmount)}</p>
                              {order.rate && <p className="text-xs text-foreground/50">₦{order.rate}/USD</p>}
                            </td>
                            <td className="px-5 py-3.5">
                              <span className={`inline-flex rounded-pill px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
                                {badge.label}
                              </span>
                            </td>
                            <td className="px-5 py-3.5 text-xs text-foreground/55">{formatTimestamp(order.createdAt)}</td>
                            <td className="px-5 py-3.5 text-right">
                              <Button
                                size="sm"
                                variant="secondary"
                                loading={busy}
                                leftIcon={<ArrowsClockwise size={14} />}
                                onClick={() => void handleReconcilePaj(order)}
                              >
                                Reconcile
                              </Button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <ul className="divide-y divide-primary/10 md:hidden">
                  {pajOrders.map((order) => {
                    const badge = getPajStatusPresentation(order.status)
                    const busy = busyPajId === order.id
                    return (
                      <li key={order.id} className="space-y-3 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-mono text-sm font-semibold text-primary">
                              {order.tokenAmount ? `${order.tokenAmount} ` : ''}
                              {order.tokenSymbol}
                            </p>
                            <p className="truncate font-mono text-xs text-foreground/60" title={order.depositAddress}>
                              {truncateAddress(order.depositAddress, 5)}
                            </p>
                          </div>
                          <span className={`inline-flex shrink-0 rounded-pill px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
                            {badge.label}
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="truncate text-xs text-foreground/65">
                            {order.bankName || '—'} · <span className="font-mono">{order.accountNumber || '—'}</span>
                          </span>
                          <span className="font-mono font-semibold tabular-nums text-primary">
                            {formatNgn(order.fiatAmount)}
                          </span>
                        </div>
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={busy}
                          leftIcon={<ArrowsClockwise size={14} />}
                          onClick={() => void handleReconcilePaj(order)}
                        >
                          Reconcile status
                        </Button>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </>
        ) : (
          <>

        {historyError && (
          <p role="alert" className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
            {historyError}
          </p>
        )}

        {historyLoading ? (
          <div className="space-y-3 p-5" role="status" aria-label="Loading fiat activity">
            {Array.from({ length: 3 }, (_, idx) => (
              <div key={idx} className="h-14 animate-pulse rounded-card bg-primary/5" />
            ))}
          </div>
        ) : visibleHistory.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-foreground/50">
            No fiat checkouts or payouts recorded yet.
          </p>
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-primary/10 bg-background text-xs font-medium text-foreground/55">
                  <tr>
                    <th className="px-5 py-3">Type</th>
                    <th className="px-5 py-3">Reference</th>
                    <th className="px-5 py-3">Bank account</th>
                    <th className="px-5 py-3">Amount</th>
                    <th className="px-5 py-3">Status</th>
                    <th className="px-5 py-3">Created</th>
                    <th className="px-5 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-primary/5">
                  {visibleHistory.map((item) => {
                    const badge = getFiatStatusPresentation(item.status, item.paymentOutcome)
                    const busy = busyRowId === item.id
                    return (
                      <tr key={item.id} className="hover:bg-primary/[0.02]">
                        <td className="px-5 py-3.5 font-medium capitalize text-foreground">{item.flow}</td>
                        <td className="px-5 py-3.5">
                          <p className="font-mono text-xs text-primary">{item.reference}</p>
                          {item.description && (
                            <p className="max-w-48 truncate text-xs text-foreground/55">{item.description}</p>
                          )}
                        </td>
                        <td className="px-5 py-3.5 text-xs">
                          <p className="font-medium text-foreground">{item.bankName || '—'}</p>
                          <p className="font-mono tabular-nums text-foreground/60">
                            {item.accountNumber || '—'} {item.accountName ? `· ${item.accountName}` : ''}
                          </p>
                        </td>
                        <td className="px-5 py-3.5 font-mono tabular-nums">
                          <p className="font-semibold text-primary">
                            {formatNgn(item.flow === 'checkout' ? item.amountPayable ?? item.amount : item.amount)}
                          </p>
                          {item.fee && <p className="text-xs text-foreground/50">Fee {formatNgn(item.fee)}</p>}
                        </td>
                        <td className="px-5 py-3.5">
                          <span className={`inline-flex rounded-pill px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-xs text-foreground/55">{formatTimestamp(item.createdAt)}</td>
                        <td className="px-5 py-3.5 text-right">
                          <div className="inline-flex items-center gap-2">
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={busy}
                              leftIcon={<ArrowsClockwise size={14} />}
                              onClick={() => void handleReconcile(item)}
                            >
                              Reconcile
                            </Button>
                            {item.flow === 'checkout' && item.status === 'pending' && (
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={busy}
                                leftIcon={<XCircle size={14} />}
                                onClick={() => void handleExpire(item)}
                              >
                                Expire
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <ul className="divide-y divide-primary/10 md:hidden">
              {visibleHistory.map((item) => {
                const badge = getFiatStatusPresentation(item.status, item.paymentOutcome)
                const busy = busyRowId === item.id
                return (
                  <li key={item.id} className="space-y-3 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold capitalize text-primary">{item.flow}</p>
                        <p className="truncate font-mono text-xs text-foreground/60">{item.reference}</p>
                      </div>
                      <span className={`inline-flex shrink-0 rounded-pill px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
                        {badge.label}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate text-xs text-foreground/65">
                        {item.bankName || '—'} · <span className="font-mono">{item.accountNumber || '—'}</span>
                      </span>
                      <span className="font-mono font-semibold tabular-nums text-primary">
                        {formatNgn(item.flow === 'checkout' ? item.amountPayable ?? item.amount : item.amount)}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={busy}
                        leftIcon={<ArrowsClockwise size={14} />}
                        onClick={() => void handleReconcile(item)}
                      >
                        Reconcile status
                      </Button>
                      {item.flow === 'checkout' && item.status === 'pending' && (
                        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void handleExpire(item)}>
                          Expire
                        </Button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        )}
          </>
        )}
      </section>
    </div>
  )
}
