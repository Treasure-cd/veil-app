import { useEffect, useMemo, useState } from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import {
  Bank,
  CheckCircle,
  Copy,
  GlobeHemisphereWest,
  Link as LinkIcon,
  LockKey,
  XCircle,
} from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { QRCodeSVG } from 'qrcode.react'
import { useAuth } from '../auth/useAuth'
import { api } from '../services/api'
import { truncateAddress } from '../lib/format'
import { IS_MAINNET, NETWORK, NETWORK_LABEL, USDC_MINT } from '../lib/network'
import { Money } from '../components/ui/Money'
import { BankAccountSetupCard } from '../components/payments/BankAccountSetupCard'
import { BankTransferCard } from '../components/payments/BankTransferCard'
import { PayoutsPanel } from '../components/payments/PayoutsPanel'
import { type FeeBearer, type FiatPayment } from '../services/fiat'
import { registerUmbraRecipient } from '../lib/umbra'
import {
  getPajRates,
  listMerchantBankAccounts,
  reconcileIntent,
  type MerchantBankAccount,
  type PaidViaRail,
  type PajOfframpOrder,
} from '../services/paj'

interface PaymentIntent {
  id: string
  amount_ngn: string
  amount_token?: string | null
  amountAtomic: string
  recipientAddress: string
  receiveMode: 'public' | 'private'
  settlementTarget?: 'crypto' | 'fiat'
  paidVia?: PaidViaRail | null
  status?: 'created' | 'funded' | 'claimed' | 'failed'
  failureReason?: string | null
  fiatCheckout?: FiatPayment | null
  pajOfframp?: PajOfframpOrder | null
  fiatPayout?: FiatPayment | { status: string; bankName?: string | null } | null
  bankAccount?: MerchantBankAccount | null
}

function getGeneratedStatusBadge(payment: {
  status: 'created' | 'funded' | 'claimed' | 'failed'
  paidVia: PaidViaRail | null
  settlementTarget: 'crypto' | 'fiat'
  receiveMode: 'public' | 'private'
  pajOfframp: PajOfframpOrder | null
  fiatPayout: FiatPayment | { status: string; bankName?: string | null } | null
  failureReason?: string | null
}): { label: string; className: string } {
  const settledStyle = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300'
  const processingStyle = 'bg-primary/10 text-primary'
  const pendingStyle = 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300'
  const failedStyle = 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300'

  if (payment.pajOfframp?.status === 'COMPLETED' || payment.fiatPayout?.status === 'completed') {
    return { label: 'Settled (NGN)', className: settledStyle }
  }
  if (payment.pajOfframp?.status === 'PROCESSING') {
    return { label: 'Processing Paj offramp', className: processingStyle }
  }
  if (payment.pajOfframp?.status === 'ERROR' || payment.fiatPayout?.status === 'failed') {
    return { label: 'Settlement error', className: failedStyle }
  }
  if (payment.settlementTarget === 'fiat' && (payment.status === 'funded' || payment.status === 'claimed')) {
    if (payment.paidVia === 'fossapay') {
      return { label: 'Sending NGN payout', className: processingStyle }
    }
    return {
      label: payment.paidVia === 'paj' ? 'Paid via Paj · Settling' : 'Paid · Settling',
      className: processingStyle,
    }
  }
  if (payment.status === 'claimed' || (payment.status === 'funded' && payment.receiveMode === 'public')) {
    return { label: 'Settled', className: settledStyle }
  }
  if (payment.status === 'funded' && payment.receiveMode === 'private') {
    return { label: 'Awaiting claim', className: pendingStyle }
  }
  if (payment.status === 'failed' && payment.failureReason === 'cancelled') {
    return { label: 'Cancelled', className: failedStyle }
  }
  if (payment.status === 'failed') {
    return { label: 'Failed', className: failedStyle }
  }
  return {
    label: payment.settlementTarget === 'fiat' ? 'Any Solana token → NGN' : 'Awaiting payment',
    className: payment.settlementTarget === 'fiat' ? settledStyle : pendingStyle,
  }
}

interface Rates {
  sol: string
  usdc: string
  asOf: string
}

type PaymentsSection = 'request' | 'payouts'

const PAJ_MIN_USDC = 0.4

export default function Payments() {
  const { user } = useAuth()
  const wallet = useWallet()
  // Standalone WhatsApp accounts have no Solana wallet, so they can only
  // receive fiat. Their buyers can still pay crypto, which Paj routes to NGN.
  const isWhatsAppAccount = Boolean(
    user?.hasWallet === false || user?.address?.startsWith('whatsapp:'),
  )
  const [section, setSection] = useState<PaymentsSection>('request')
  const [amount, setAmount] = useState('')
  const token = 'USDC'
  const [rate, setRate] = useState<string | null>(null)
  const [rateError, setRateError] = useState(false)
  const [memo, setMemo] = useState('')
  const [includeFiatCheckout, setIncludeFiatCheckout] = useState(true)
  const [feeBearer, setFeeBearer] = useState<FeeBearer>('customer')
  const [settlementTarget, setSettlementTarget] = useState<'crypto' | 'fiat'>('crypto')
  const [receiveMode, setReceiveMode] = useState<'public' | 'private'>('public')
  const [bankAccounts, setBankAccounts] = useState<MerchantBankAccount[]>([])
  const [selectedBankAccountId, setSelectedBankAccountId] = useState('')
  const [bankAccountsLoading, setBankAccountsLoading] = useState(true)
  const [showAddBankForm, setShowAddBankForm] = useState(false)
  const [pajRate, setPajRate] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [checkingFiat, setCheckingFiat] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [generatedLink, setGeneratedLink] = useState<string | null>(null)
  const [generatedPayment, setGeneratedPayment] = useState<{
    id: string
    amountNgn: string
    tokenAmount: string
    status: 'created' | 'funded' | 'claimed' | 'failed'
    failureReason?: string | null
    paidVia: PaidViaRail | null
    fiatCheckout: FiatPayment | null
    pajOfframp: PajOfframpOrder | null
    fiatPayout: FiatPayment | { status: string; bankName?: string | null } | null
    settlementTarget: 'crypto' | 'fiat'
    recipientAddress: string
    receiveMode: 'public' | 'private'
    bankAccount: MerchantBankAccount | null
  } | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedDeposit, setCopiedDeposit] = useState(false)

  useEffect(() => {
    if (settlementTarget === 'fiat') setReceiveMode('public')
  }, [settlementTarget])

  useEffect(() => {
    if (isWhatsAppAccount) setSettlementTarget('fiat')
  }, [isWhatsAppAccount])

  useEffect(() => {
    let active = true
    const loadRate = async () => {
      try {
        const rates = await api<Rates>('/v1/rates')
        if (active) {
          setRate(rates.usdc)
          setRateError(false)
        }
      } catch {
        if (active) setRateError(true)
      }
    }
    const loadPajState = async () => {
      setBankAccountsLoading(true)
      try {
        const [accounts, pajRates] = await Promise.all([
          listMerchantBankAccounts().catch(() => [] as MerchantBankAccount[]),
          getPajRates().catch(() => null),
        ])
        if (!active) return
        setBankAccounts(accounts)
        const preferred = accounts.find((acc) => acc.isDefault) ?? accounts[0]
        setSelectedBankAccountId(preferred?.id ?? '')
        if (pajRates?.offRampRate?.rate) {
          setPajRate(pajRates.offRampRate.rate)
        }
      } finally {
        if (active) setBankAccountsLoading(false)
      }
    }
    void loadRate()
    void loadPajState()
    const interval = window.setInterval(() => void loadRate(), 60_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  const selectedBankAccount = useMemo(
    () =>
      bankAccounts.find((acc) => acc.id === selectedBankAccountId) ??
      bankAccounts.find((acc) => acc.isDefault) ??
      bankAccounts[0] ??
      null,
    [bankAccounts, selectedBankAccountId],
  )

  function handleBankAccountsChanged(accounts: MerchantBankAccount[]) {
    setBankAccounts(accounts)
    setSelectedBankAccountId((current) => {
      if (accounts.some((acc) => acc.id === current)) return current
      return (accounts.find((acc) => acc.isDefault) ?? accounts[0])?.id ?? ''
    })
    if (accounts.length > 0) setShowAddBankForm(false)
  }

  const tokenEstimate = useMemo(() => {
    const ngn = Number(amount)
    const ngnPerToken = Number(rate)
    return Number.isFinite(ngn) && ngn > 0 && Number.isFinite(ngnPerToken) && ngnPerToken > 0
      ? (ngn / ngnPerToken).toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
      : null
  }, [amount, rate])

  const effectivePajRate = useMemo(() => {
    if (pajRate && Number.isFinite(pajRate) && pajRate > 0) return pajRate
    const fallback = rate ? Number(rate) : NaN
    return Number.isFinite(fallback) && fallback > 0 ? fallback : null
  }, [pajRate, rate])

  const pajMinNgn = useMemo(() => {
    if (!effectivePajRate) return null
    return Math.ceil(PAJ_MIN_USDC * effectivePajRate)
  }, [effectivePajRate])

  const parsedAmount = Number(amount)
  const belowPajMin = Boolean(
    settlementTarget === 'fiat' &&
      pajMinNgn !== null &&
      amount.trim() !== '' &&
      Number.isFinite(parsedAmount) &&
      parsedAmount >= 0 &&
      parsedAmount < pajMinNgn,
  )

  async function handleGenerate() {
    const includeBankTransfer = includeFiatCheckout &&
      !(settlementTarget === 'crypto' && receiveMode === 'private')
    setError(null)
    if (!/^\d+(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {
      setError('Enter a positive naira amount with up to two decimal places.')
      return
    }
    if (includeBankTransfer && (!/^\d+$/.test(amount.trim()) || Number(amount) < 1)) {
      setError('Bank transfer checkouts require a whole-naira amount (no kobo decimals) of at least ₦1.')
      return
    }
    if (settlementTarget === 'fiat' && pajMinNgn !== null && Number(amount) < pajMinNgn) {
      setError(
        `Paj Cash NGN settlement requires at least ₦${pajMinNgn.toLocaleString('en-NG')} (0.40 USDC equivalent).`,
      )
      return
    }
    if (!rate) {
      setError('The live exchange rate is unavailable. Try again shortly.')
      return
    }
    if (!user?.address) {
      setError('Sign in to create a payment request.')
      return
    }
    if (settlementTarget === 'crypto' && isWhatsAppAccount) {
      setError('WhatsApp-only accounts cannot receive crypto directly. Link a Nigerian bank account to settle in NGN.')
      return
    }
    if (settlementTarget === 'fiat' && !selectedBankAccount) {
      setError('Link a Nigerian bank account below before creating a fiat-settled payment link.')
      return
    }
    if (
      settlementTarget === 'crypto' &&
      receiveMode === 'private' &&
      (!wallet.connected || wallet.publicKey?.toBase58() !== user.address)
    ) {
      setError('Connect the merchant wallet receiving this payment to set up its Umbra account.')
      return
    }

    setIsLoading(true)
    try {
      if (settlementTarget === 'crypto' && receiveMode === 'private') {
        await registerUmbraRecipient({ wallet })
      }
      const intent = await api<PaymentIntent>('/v1/payments/intents', {
        method: 'POST',
        body: JSON.stringify({
          merchantRef: `INV-${Date.now()}`,
          token,
          amount_ngn: amount,
          recipientAddress:
            settlementTarget === 'fiat'
              ? selectedBankAccount?.solanaAddress ?? user.address
              : user.address,
          receiveMode: settlementTarget === 'crypto' ? receiveMode : 'public',
          memo: memo.trim() || 'Payment request',
          includeFiatCheckout: includeBankTransfer,
          feeBearer,
          settlementTarget,
          ...(settlementTarget === 'fiat' && selectedBankAccount
            ? { bankAccountId: selectedBankAccount.id }
            : {}),
        }),
      })
      if (!intent.id) throw new Error('The payment request was created without an ID.')
      setGeneratedPayment({
        id: intent.id,
        amountNgn: intent.amount_ngn,
        tokenAmount:
          intent.amount_token ??
          (Number(intent.amountAtomic) / 1e6).toString(),
        status: intent.status ?? 'created',
        failureReason: intent.failureReason ?? null,
        paidVia: intent.paidVia ?? null,
        fiatCheckout: intent.fiatCheckout ?? null,
        pajOfframp: intent.pajOfframp ?? null,
        fiatPayout: intent.fiatPayout ?? null,
        settlementTarget: intent.settlementTarget ?? settlementTarget,
        recipientAddress: intent.recipientAddress,
        receiveMode: intent.receiveMode ?? (settlementTarget === 'crypto' ? receiveMode : 'public'),
        bankAccount: intent.bankAccount ?? (settlementTarget === 'fiat' ? selectedBankAccount : null),
      })
      setGeneratedLink(new URL(`/pay/${intent.id}`, window.location.origin).toString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the payment request.')
    } finally {
      setIsLoading(false)
    }
  }

  async function copyDepositAddress(address: string) {
    try {
      await navigator.clipboard.writeText(address)
      setCopiedDeposit(true)
      window.setTimeout(() => setCopiedDeposit(false), 2000)
    } catch {
      setError('Could not copy the deposit address.')
    }
  }

  async function reconcileGeneratedIntent() {
    if (!generatedPayment) return
    setCheckingFiat(true)
    setError(null)
    try {
      const updated = await reconcileIntent(generatedPayment.id)
      setGeneratedPayment((prev) =>
        prev
          ? {
              ...prev,
              status: updated.status,
              paidVia: updated.paidVia,
              fiatCheckout: updated.fiatCheckout,
              pajOfframp: updated.pajOfframp,
              fiatPayout: updated.fiatPayout ?? null,
            }
          : prev,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reconcile payment status.')
    } finally {
      setCheckingFiat(false)
    }
  }

  async function cancelGeneratedIntent() {
    if (!generatedPayment || generatedPayment.status !== 'created') return
    if (!window.confirm('Cancel this unpaid payment link? Customers will no longer be able to pay it.')) return
    setCancelling(true)
    setError(null)
    try {
      const cancelled = await api<PaymentIntent>(`/v1/payments/intents/${generatedPayment.id}/cancel`, {
        method: 'POST',
      })
      setGeneratedPayment((prev) =>
        prev
          ? {
              ...prev,
              status: cancelled.status ?? 'failed',
              failureReason: cancelled.failureReason ?? 'cancelled',
            }
          : prev,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel the payment link.')
    } finally {
      setCancelling(false)
    }
  }

  async function copyLink() {
    if (!generatedLink) return
    try {
      await navigator.clipboard.writeText(generatedLink)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy the link. You can select and copy it manually.')
    }
  }

  return (
    <div className="w-full space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-primary">
            {section === 'request' ? 'Request payment' : 'NGN payouts'}
          </h1>
          <p className="mt-1 text-sm text-foreground/70">
            {section === 'request'
              ? 'Create a checkout link customers can pay via Nigerian bank transfer or a connected Solana wallet.'
              : 'Send NGN from your FossaPay master wallet to a verified Nigerian bank account and track fiat activity.'}
          </p>
        </div>

        <div
          className="inline-flex rounded-pill border border-primary/10 bg-surface p-1 shadow-veil-sm"
          role="tablist"
          aria-label="Payment workspace"
        >
          <button
            type="button"
            role="tab"
            aria-selected={section === 'request'}
            onClick={() => setSection('request')}
            className={`min-h-9 rounded-pill px-4 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              section === 'request' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            Request payment
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={section === 'payouts'}
            onClick={() => setSection('payouts')}
            className={`min-h-9 rounded-pill px-4 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              section === 'payouts' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            NGN payouts
          </button>
        </div>
      </header>

      {section === 'payouts' ? (
        <PayoutsPanel />
      ) : generatedLink ? (
        <div className="mx-auto max-w-2xl">
          <section className="rounded-panel border border-primary/10 bg-surface p-6 text-center shadow-veil-sm sm:p-8">
            <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
              <CheckCircle size={30} weight="fill" />
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-tight text-primary">Payment link ready</h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-foreground/65">
              {generatedPayment?.settlementTarget === 'fiat' ? (
                <>
                  Share this checkout link. Your customer can pay with USDC, SOL, USDT, USDG
                  {generatedPayment.fiatCheckout ? ', or Nigerian bank transfer' : ''}; crypto deposits settle in NGN
                  to{' '}
                  {generatedPayment.bankAccount
                    ? `${generatedPayment.bankAccount.bankName} · ${generatedPayment.bankAccount.accountNumber}`
                    : 'your linked bank account'}.
                </>
              ) : generatedPayment?.receiveMode === 'private' ? (
                <>
                  Share this checkout link. Payments are routed through Umbra to your private receiving account.
                  The sender wallet and amount remain visible in the Umbra deposit transaction, but are not linked
                  there to your merchant account.
                </>
              ) : (
                <>
                  Share this checkout link. Your customer does not need a Veil account and can pay via{' '}
                  {generatedPayment?.fiatCheckout ? 'bank transfer or a Solana wallet' : 'a Solana wallet'}.
                </>
              )}
            </p>
            {generatedPayment?.receiveMode === 'private' && (
              <span className="mt-3 inline-flex rounded-pill bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-900 dark:bg-amber-500/15 dark:text-amber-300">
                Private · Umbra
              </span>
            )}
            {generatedPayment && (
              <div className="mt-4 flex justify-center">
                <Money
                  amountNgn={generatedPayment.amountNgn}
                  tokenAmount={generatedPayment.tokenAmount}
                  token="USDC"
                  primaryClassName="text-xl font-semibold"
                />
              </div>
            )}
            <div className="mx-auto mt-6 flex w-fit rounded-xl border border-primary/10 bg-white p-3 shadow-sm">
              <QRCodeSVG value={generatedLink} size={176} level="M" includeMargin aria-label="QR code for payment link" />
            </div>
            <p className="mt-2 text-xs text-foreground/55">Scan to open checkout</p>
            <div className="mx-auto mt-6 flex max-w-lg items-center gap-2 rounded-card border border-primary/15 bg-background p-2">
              <input
                aria-label="Payment link"
                readOnly
                value={generatedLink}
                className="min-w-0 flex-1 bg-transparent px-2 text-left text-sm text-primary outline-none"
              />
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void copyLink()}
                leftIcon={copied ? <CheckCircle size={16} /> : <Copy size={16} />}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>

            {generatedPayment?.settlementTarget === 'fiat' && (
              <div className="mx-auto mt-6 max-w-lg rounded-card border border-primary/15 bg-background p-4 text-left">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-primary">Auto-offramp to Nigerian bank (Paj Cash)</p>
                  <span className={`rounded-pill px-2.5 py-0.5 text-xs font-medium ${getGeneratedStatusBadge(generatedPayment).className}`}>
                    {getGeneratedStatusBadge(generatedPayment).label}
                  </span>
                </div>
                {generatedPayment.bankAccount && (
                  <p className="mt-1 text-xs text-foreground/70">
                    {generatedPayment.bankAccount.bankName} ·{' '}
                    <span className="font-mono tabular-nums">{generatedPayment.bankAccount.accountNumber}</span>
                    {generatedPayment.bankAccount.accountName ? ` · ${generatedPayment.bankAccount.accountName}` : ''}
                  </p>
                )}
                <div className="mt-3 flex items-center justify-between gap-2 rounded-card border border-primary/10 bg-surface px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-[11px] uppercase tracking-wider text-foreground/50">
                      {IS_MAINNET
                        ? 'Permanent Solana Mainnet deposit address'
                        : 'Permanent Paj Cash deposit address (Solana Mainnet)'}
                    </p>
                    <p className="truncate font-mono text-xs text-primary">{generatedPayment.recipientAddress}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void copyDepositAddress(generatedPayment.recipientAddress)}
                    leftIcon={copiedDeposit ? <CheckCircle size={14} /> : <Copy size={14} />}
                  >
                    {copiedDeposit ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                {!generatedPayment.fiatCheckout && (
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <span className="text-xs text-foreground/60">
                      {generatedPayment.paidVia === 'paj' && generatedPayment.pajOfframp?.tokenAmount
                        ? `Paid ${generatedPayment.pajOfframp.tokenAmount} ${generatedPayment.pajOfframp.tokenSymbol} via Paj`
                        : 'Check crypto or Paj offramp settlement'}
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={checkingFiat}
                      onClick={() => void reconcileGeneratedIntent()}
                    >
                      {checkingFiat ? 'Checking...' : 'Reconcile payment status'}
                    </Button>
                  </div>
                )}
              </div>
            )}

            {generatedPayment && generatedPayment.settlementTarget !== 'fiat' && !generatedPayment.fiatCheckout && (
              <div className="mx-auto mt-6 flex max-w-lg flex-wrap items-center justify-between gap-3 rounded-card border border-primary/15 bg-background px-4 py-3 text-left">
                <span className={`rounded-pill px-2.5 py-0.5 text-xs font-medium ${getGeneratedStatusBadge(generatedPayment).className}`}>
                  {getGeneratedStatusBadge(generatedPayment).label}
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={checkingFiat}
                  onClick={() => void reconcileGeneratedIntent()}
                >
                  {checkingFiat ? 'Checking...' : 'Reconcile payment status'}
                </Button>
              </div>
            )}

            {generatedPayment?.fiatCheckout && (
              <div className="mx-auto mt-6 max-w-lg">
                <BankTransferCard
                  checkout={generatedPayment.fiatCheckout}
                  compact
                  checkingStatus={checkingFiat}
                  reconcileLabel="Reconcile payment status"
                  onCheckStatus={() => void reconcileGeneratedIntent()}
                />
              </div>
            )}

            {error && <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
            {generatedPayment?.status === 'created' && (
              <Button
                className="mt-6"
                variant="secondary"
                loading={cancelling}
                onClick={() => void cancelGeneratedIntent()}
                leftIcon={<XCircle size={17} />}
              >
                Cancel payment link
              </Button>
            )}
            <Button
              className="mt-6"
              variant="secondary"
              onClick={() => {
                setGeneratedLink(null)
                setGeneratedPayment(null)
                setAmount('')
                setMemo('')
                setError(null)
              }}
            >
              Create another request
            </Button>
          </section>
        </div>
      ) : (
        <>
          {error && (
            <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-950/45 dark:text-red-300">
              {error}
            </p>
          )}

          <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr] 2xl:grid-cols-[1.3fr_0.7fr]">
            <section className="space-y-5 rounded-panel border border-primary/10 bg-surface p-5 shadow-veil-sm sm:p-6">
              <div className="space-y-1.5">
                <label htmlFor="payment-memo" className="text-sm font-medium">Description</label>
                <input
                  id="payment-memo"
                  type="text"
                  maxLength={120}
                  placeholder="e.g. Website design"
                  value={memo}
                  onChange={(event) => setMemo(event.target.value)}
                  className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label htmlFor="payment-amount" className="text-sm font-medium">Amount (NGN)</label>
                  <input
                    id="payment-amount"
                    type="number"
                    min={settlementTarget === 'fiat' && pajMinNgn ? String(pajMinNgn) : '0'}
                    step={includeFiatCheckout && receiveMode !== 'private' ? '1' : 'any'}
                    inputMode={includeFiatCheckout && receiveMode !== 'private' ? 'numeric' : 'decimal'}
                    placeholder={
                      settlementTarget === 'fiat' && pajMinNgn
                        ? String(Math.max(5000, pajMinNgn))
                        : includeFiatCheckout && receiveMode !== 'private'
                          ? '5000'
                          : '0.00'
                    }
                    aria-invalid={belowPajMin ? true : undefined}
                    aria-describedby={settlementTarget === 'fiat' && pajMinNgn !== null ? 'payment-amount-paj-hint' : undefined}
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    className={`h-11 w-full rounded-card border bg-background px-3 font-mono text-sm outline-none transition focus:ring-2 ${
                      belowPajMin
                        ? 'border-amber-500/60 focus:border-amber-600 focus:ring-amber-500/15'
                        : 'border-primary/15 focus:border-primary/40 focus:ring-primary/10'
                    }`}
                  />
                  {settlementTarget === 'fiat' && pajMinNgn !== null && (
                    belowPajMin ? (
                      <p id="payment-amount-paj-hint" role="alert" className="text-xs font-medium text-amber-700 dark:text-amber-300">
                        Minimum for Paj Cash NGN settlement is ₦{pajMinNgn.toLocaleString('en-NG')} (0.40 USDC equivalent).
                      </p>
                    ) : (
                      <p id="payment-amount-paj-hint" className="text-xs text-foreground/55">
                        Min. ₦{pajMinNgn.toLocaleString('en-NG')} (0.40 USDC) for Paj Cash NGN settlement.
                      </p>
                    )
                  )}
                </div>
                <div className="space-y-1.5">
                  <span className="text-sm font-medium">Rails</span>
                  <div
                    title={`Active USDC contract: ${USDC_MINT}`}
                    className="flex h-11 items-center rounded-card border border-primary/15 bg-primary/5 px-3 text-sm font-medium text-primary"
                  >
                    {settlementTarget === 'fiat'
                      ? `${includeFiatCheckout ? 'Fiat Bank Transfer · ' : ''}Multi-token Solana → NGN`
                      : receiveMode === 'private'
                        ? `Private USDC · Umbra (${NETWORK_LABEL[NETWORK]})`
                        : includeFiatCheckout
                        ? `Fiat Bank Transfer · USDC (${NETWORK_LABEL[NETWORK]})`
                        : `NGN → USDC · ${NETWORK_LABEL[NETWORK]}`}
                  </div>
                </div>
              </div>

              {!(settlementTarget === 'crypto' && receiveMode === 'private') && (
              <div className="border-t border-primary/10 pt-5">
                <p className="text-sm font-medium">Buyer payment options</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <button
                    type="button"
                    aria-pressed={includeFiatCheckout}
                    onClick={() => setIncludeFiatCheckout(true)}
                    className={`rounded-card border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      includeFiatCheckout
                        ? 'border-primary/35 bg-primary/5'
                        : 'border-primary/10 bg-background hover:border-primary/25'
                    }`}
                  >
                    <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                      <Bank size={17} weight="fill" /> Fiat (Bank transfer) + Crypto
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      Buyers can pay by Nigerian bank transfer or a Solana wallet on the checkout link.
                    </p>
                  </button>
                  <button
                    type="button"
                    aria-pressed={!includeFiatCheckout}
                    onClick={() => setIncludeFiatCheckout(false)}
                    className={`rounded-card border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      !includeFiatCheckout
                        ? 'border-primary/35 bg-primary/5'
                        : 'border-primary/10 bg-background hover:border-primary/25'
                    }`}
                  >
                    <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                      <GlobeHemisphereWest size={17} /> Crypto wallet only
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      On-chain crypto checkout only (whole Naira links can still offer bank transfer later). Supports kobo decimals.
                    </p>
                  </button>
                </div>

                {includeFiatCheckout && (
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-primary/10 bg-background px-4 py-3">
                    <div>
                      <p className="text-xs font-semibold text-foreground">Bank transfer fee</p>
                      <p className="text-xs text-foreground/55">Choose who absorbs the FossaPay checkout fee</p>
                    </div>
                    <div className="inline-flex rounded-pill border border-primary/10 bg-surface p-0.5" role="group" aria-label="Checkout fee bearer">
                      {(['customer', 'merchant'] as const).map((option) => (
                        <button
                          key={option}
                          type="button"
                          aria-pressed={feeBearer === option}
                          onClick={() => setFeeBearer(option)}
                          className={`min-h-8 rounded-pill px-3 text-xs font-semibold capitalize transition-colors ${
                            feeBearer === option ? 'bg-primary-action text-white' : 'text-foreground/60 hover:text-primary'
                          }`}
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              )}

              <div className="border-t border-primary/10 pt-5">
                <p className="text-sm font-medium">How you receive funds</p>
                {isWhatsAppAccount && (
                  <p className="mt-1 text-xs leading-relaxed text-foreground/55">
                    WhatsApp accounts settle to your Nigerian bank account. Buyers can still pay with crypto; Paj Cash
                    converts it to NGN for you.
                  </p>
                )}
                <div className={`mt-3 grid gap-3 ${isWhatsAppAccount ? '' : 'sm:grid-cols-2'}`}>
                  {!isWhatsAppAccount && (
                    <button
                      type="button"
                      aria-pressed={settlementTarget === 'crypto'}
                      onClick={() => setSettlementTarget('crypto')}
                      className={`rounded-card border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                        settlementTarget === 'crypto'
                          ? 'border-primary/35 bg-primary/5'
                          : 'border-primary/10 bg-background hover:border-primary/25'
                      }`}
                    >
                      <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                        <GlobeHemisphereWest size={17} /> Receive Crypto (USDC)
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                        {user?.address
                          ? `Crypto transfers land directly in your wallet (${truncateAddress(user.address)}).`
                          : 'Crypto transfers settle directly into your connected Solana wallet.'}
                      </p>
                    </button>
                  )}
                  <button
                    type="button"
                    aria-pressed={settlementTarget === 'fiat'}
                    onClick={() => setSettlementTarget('fiat')}
                    className={`rounded-card border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      settlementTarget === 'fiat'
                        ? 'border-primary/35 bg-primary/5'
                        : 'border-primary/10 bg-background hover:border-primary/25'
                    }`}
                  >
                    <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                      <Bank size={17} weight="fill" /> Receive Fiat / NGN (Paj Cash)
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      Payers can send USDC, SOL, USDT, USDG, or bank transfer; crypto routes through Paj Cash to settle NGN directly to your Nigerian bank account.
                    </p>
                  </button>
                </div>

                {settlementTarget === 'fiat' && (
                  <div className="mt-4 space-y-3">
                    {bankAccountsLoading ? (
                      <div className="h-20 animate-pulse rounded-card bg-primary/5" role="status" aria-label="Loading linked bank accounts" />
                    ) : bankAccounts.length > 0 ? (
                      <div className="space-y-3 rounded-card border border-primary/15 bg-background p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <label htmlFor="paj-bank-account-select" className="text-xs font-semibold text-primary">
                            Destination Nigerian bank account
                          </label>
                          <button
                            type="button"
                            onClick={() => setShowAddBankForm((open) => !open)}
                            className="text-xs font-medium text-primary underline underline-offset-2 hover:text-primary/80"
                          >
                            {showAddBankForm ? 'Hide registration form' : '+ Link another account'}
                          </button>
                        </div>
                        <select
                          id="paj-bank-account-select"
                          value={selectedBankAccount?.id ?? ''}
                          onChange={(event) => setSelectedBankAccountId(event.target.value)}
                          className="h-10 w-full rounded-card border border-primary/15 bg-surface px-3 text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                        >
                          {bankAccounts.map((acc) => (
                            <option key={acc.id} value={acc.id}>
                              {acc.bankName} · {acc.accountNumber} · {acc.accountName}
                              {acc.isDefault ? ' (Default)' : ''}
                            </option>
                          ))}
                        </select>
                        {selectedBankAccount?.solanaAddress && (
                          <p className="text-xs text-foreground/60">
                            Auto-offramp address:{' '}
                            <span className="font-mono text-primary">
                              {truncateAddress(selectedBankAccount.solanaAddress, 6)}
                            </span>
                            {' · '}
                            {IS_MAINNET
                              ? `Solana Mainnet tokens deposited here settle to ${selectedBankAccount.bankName}.`
                              : `App is on ${NETWORK_LABEL[NETWORK]}; Paj Cash settles Mainnet deposits to ${selectedBankAccount.bankName}.`}
                          </p>
                        )}
                        {showAddBankForm && (
                          <div className="pt-2">
                            <BankAccountSetupCard compact onAccountChanged={handleBankAccountsChanged} />
                          </div>
                        )}
                      </div>
                    ) : (
                      <BankAccountSetupCard compact onAccountChanged={handleBankAccountsChanged} />
                    )}
                  </div>
                )}

                {settlementTarget === 'crypto' && (
                  <div className="mt-4">
                    <p className="text-sm font-medium">Receiving privacy</p>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2" role="group" aria-label="Receiving privacy mode">
                      <button
                        type="button"
                        aria-pressed={receiveMode === 'public'}
                        onClick={() => setReceiveMode('public')}
                        className={`rounded-card border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                          receiveMode === 'public'
                            ? 'border-primary/35 bg-primary/5'
                            : 'border-primary/10 bg-background hover:border-primary/25'
                        }`}
                      >
                        <p className="text-sm font-semibold text-primary">Public</p>
                        <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                          Direct on-chain transfer to your wallet.
                        </p>
                      </button>
                      <button
                        type="button"
                        aria-pressed={receiveMode === 'private'}
                        onClick={() => setReceiveMode('private')}
                        className={`rounded-card border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                          receiveMode === 'private'
                            ? 'border-amber-500/45 bg-amber-50 dark:bg-amber-950/35'
                            : 'border-primary/10 bg-background hover:border-primary/25'
                        }`}
                      >
                        <p className="flex items-center gap-1.5 text-sm font-semibold text-primary">
                          <LockKey size={15} aria-hidden="true" /> Private (Umbra)
                        </p>
                        <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                          Umbra shields the receiving account link. The sender wallet and amount remain visible in the deposit transaction.
                        </p>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </section>

            <aside className="flex flex-col rounded-panel border border-primary/10 bg-primary/[0.035] p-5 sm:p-6">
              <h2 className="text-lg font-semibold text-primary">Summary</h2>
              <div className="flex flex-1 flex-col items-center justify-center py-8 text-center">
                <p className="text-sm text-foreground/60">Requesting</p>
                <Money
                  amountNgn={amount && Number(amount) > 0 ? amount : 0}
                  tokenAmount={tokenEstimate}
                  token={token}
                  className="my-2 max-w-full break-all text-4xl font-semibold tracking-tight text-primary"
                  primaryClassName="text-4xl"
                />
                <span className="mt-1 inline-flex rounded-pill bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                  {settlementTarget === 'fiat' ? 'Settles to NGN Bank (Paj Cash)' : 'Settles to Crypto Wallet'}
                </span>
                {settlementTarget === 'crypto' && receiveMode === 'private' && (
                  <span className="mt-2 inline-flex rounded-pill bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-900 dark:bg-amber-500/15 dark:text-amber-300">
                    Private · Umbra
                  </span>
                )}
                <p className="mt-2 text-xs text-foreground/50">
                  {rate ? 'Live estimate · rate locks for 30 minutes' : rateError ? 'Rate unavailable' : 'Loading live rate…'}
                </p>
                {settlementTarget === 'fiat' && pajRate && (
                  <p className="mt-1 font-mono text-xs text-foreground/60 tabular-nums">
                    Paj offramp reference: ₦{pajRate.toLocaleString('en-NG')}/USD
                  </p>
                )}
                <p className="mt-1 max-w-full break-words text-sm text-foreground/70">{memo.trim() || 'Payment request'}</p>
              </div>
              <Button
                size="lg"
                fullWidth
                loading={isLoading}
                onClick={() => void handleGenerate()}
                leftIcon={<LinkIcon size={19} weight="bold" />}
              >
                Generate payment link
              </Button>
              <p className="mt-3 text-center text-xs text-foreground/55">
                Link creation requires your Veil merchant account.
              </p>
            </aside>
          </div>
        </>
      )}
    </div>
  )
}
