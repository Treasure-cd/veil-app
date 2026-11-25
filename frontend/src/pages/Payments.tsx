import { useEffect, useMemo, useState } from 'react'
import {
  Bank,
  CheckCircle,
  Copy,
  GlobeHemisphereWest,
  Link as LinkIcon,
  LockKey,
} from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { QRCodeSVG } from 'qrcode.react'
import { useAuth } from '../auth/useAuth'
import { api } from '../services/api'
import { NETWORK, NETWORK_LABEL } from '../lib/network'
import { Money } from '../components/ui/Money'
import { BankTransferCard } from '../components/payments/BankTransferCard'
import { PayoutsPanel } from '../components/payments/PayoutsPanel'
import { reconcileFiatPayment, type FeeBearer, type FiatPayment } from '../services/fiat'

interface PaymentIntent {
  id: string
  amount_ngn: string
  amountAtomic: string
  fiatCheckout?: FiatPayment | null
}

interface Rates {
  sol: string
  usdc: string
  asOf: string
}

type PaymentsSection = 'request' | 'payouts'

export default function Payments() {
  const { user } = useAuth()
  const [section, setSection] = useState<PaymentsSection>('request')
  const [amount, setAmount] = useState('')
  const token = 'USDC'
  const [rate, setRate] = useState<string | null>(null)
  const [rateError, setRateError] = useState(false)
  const [memo, setMemo] = useState('')
  const [includeFiatCheckout, setIncludeFiatCheckout] = useState(true)
  const [feeBearer, setFeeBearer] = useState<FeeBearer>('customer')
  const [isLoading, setIsLoading] = useState(false)
  const [checkingFiat, setCheckingFiat] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [generatedLink, setGeneratedLink] = useState<string | null>(null)
  const [generatedPayment, setGeneratedPayment] = useState<{
    amountNgn: string
    tokenAmount: string
    fiatCheckout: FiatPayment | null
  } | null>(null)
  const [copied, setCopied] = useState(false)

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
    void loadRate()
    const interval = window.setInterval(() => void loadRate(), 60_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  const tokenEstimate = useMemo(() => {
    const ngn = Number(amount)
    const ngnPerToken = Number(rate)
    return Number.isFinite(ngn) && ngn > 0 && Number.isFinite(ngnPerToken) && ngnPerToken > 0
      ? (ngn / ngnPerToken).toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
      : null
  }, [amount, rate])

  async function handleGenerate() {
    setError(null)
    if (!/^\d+(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {
      setError('Enter a positive naira amount with up to two decimal places.')
      return
    }
    if (includeFiatCheckout && (!/^\d+$/.test(amount.trim()) || Number(amount) < 1)) {
      setError('Bank transfer checkouts require a whole-naira amount (no kobo decimals) of at least ₦1.')
      return
    }
    if (!rate) {
      setError('The live exchange rate is unavailable. Try again shortly.')
      return
    }
    if (!user?.address) {
      setError('Sign in with the wallet that should receive this payment.')
      return
    }

    setIsLoading(true)
    try {
      const intent = await api<PaymentIntent>('/v1/payments/intents', {
        method: 'POST',
        body: JSON.stringify({
          merchantRef: `INV-${Date.now()}`,
          token,
          amount_ngn: amount,
          recipientAddress: user.address,
          receiveMode: 'public',
          memo: memo.trim() || 'Payment request',
          includeFiatCheckout,
          feeBearer,
        }),
      })
      if (!intent.id) throw new Error('The payment request was created without an ID.')
      setGeneratedPayment({
        amountNgn: intent.amount_ngn,
        tokenAmount: (Number(intent.amountAtomic) / 1e6).toString(),
        fiatCheckout: intent.fiatCheckout ?? null,
      })
      setGeneratedLink(new URL(`/pay/${intent.id}`, window.location.origin).toString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the payment request.')
    } finally {
      setIsLoading(false)
    }
  }

  async function refreshGeneratedFiatCheckout() {
    if (!generatedPayment?.fiatCheckout) return
    setCheckingFiat(true)
    setError(null)
    try {
      const updated = await reconcileFiatPayment(generatedPayment.fiatCheckout.id)
      setGeneratedPayment((prev) => (prev ? { ...prev, fiatCheckout: updated } : prev))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not refresh bank transfer status.')
    } finally {
      setCheckingFiat(false)
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
    <div className="mx-auto max-w-5xl space-y-6">
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
          className="inline-flex rounded-pill border border-primary/10 bg-white p-1 shadow-veil-sm"
          role="tablist"
          aria-label="Payment workspace"
        >
          <button
            type="button"
            role="tab"
            aria-selected={section === 'request'}
            onClick={() => setSection('request')}
            className={`min-h-9 rounded-pill px-4 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              section === 'request' ? 'bg-primary text-white' : 'text-foreground/65 hover:text-primary'
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
              section === 'payouts' ? 'bg-primary text-white' : 'text-foreground/65 hover:text-primary'
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
          <section className="rounded-panel border border-primary/10 bg-white p-6 text-center shadow-veil-sm sm:p-8">
            <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <CheckCircle size={30} weight="fill" />
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-tight text-primary">Payment link ready</h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-foreground/65">
              Share this checkout link. Your customer does not need a Veil account and can pay via{' '}
              {generatedPayment?.fiatCheckout ? 'bank transfer or a Solana wallet' : 'a Solana wallet'}.
            </p>
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

            {generatedPayment?.fiatCheckout && (
              <div className="mx-auto mt-6 max-w-lg">
                <BankTransferCard
                  checkout={generatedPayment.fiatCheckout}
                  compact
                  checkingStatus={checkingFiat}
                  reconcileLabel="Reconcile payment status"
                  onCheckStatus={() => void refreshGeneratedFiatCheckout()}
                />
              </div>
            )}

            {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
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
            <p role="alert" className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          )}

          <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
            <section className="space-y-5 rounded-panel border border-primary/10 bg-white p-5 shadow-veil-sm sm:p-6">
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
                    min="0"
                    step={includeFiatCheckout ? '1' : 'any'}
                    inputMode={includeFiatCheckout ? 'numeric' : 'decimal'}
                    placeholder={includeFiatCheckout ? '5000' : '0.00'}
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                  />
                </div>
                <div className="space-y-1.5">
                  <span className="text-sm font-medium">Rails</span>
                  <div className="flex h-11 items-center rounded-card border border-primary/15 bg-primary/5 px-3 text-sm font-medium text-primary">
                    {includeFiatCheckout
                      ? `NGN Bank Transfer · USDC (${NETWORK_LABEL[NETWORK]})`
                      : `NGN → USDC · ${NETWORK_LABEL[NETWORK]}`}
                  </div>
                </div>
              </div>

              <div className="border-t border-primary/10 pt-5">
                <p className="text-sm font-medium">Payment channels</p>
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
                      <Bank size={17} weight="fill" /> Bank transfer + USDC
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      Generates a 30-minute Nigerian virtual bank account alongside Solana USDC checkout.
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
                      <GlobeHemisphereWest size={17} /> Solana USDC only
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      On-chain USDC checkout only. Supports kobo decimals.
                    </p>
                  </button>
                </div>

                {includeFiatCheckout && (
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-primary/10 bg-background px-4 py-3">
                    <div>
                      <p className="text-xs font-semibold text-foreground">Bank transfer fee</p>
                      <p className="text-xs text-foreground/55">Choose who absorbs the FossaPay checkout fee</p>
                    </div>
                    <div className="inline-flex rounded-pill border border-primary/10 bg-white p-0.5" role="group" aria-label="Checkout fee bearer">
                      {(['customer', 'merchant'] as const).map((option) => (
                        <button
                          key={option}
                          type="button"
                          aria-pressed={feeBearer === option}
                          onClick={() => setFeeBearer(option)}
                          className={`min-h-8 rounded-pill px-3 text-xs font-semibold capitalize transition-colors ${
                            feeBearer === option ? 'bg-primary text-white' : 'text-foreground/60 hover:text-primary'
                          }`}
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="border-t border-primary/10 pt-5">
                <p className="text-sm font-medium">Settlement</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-card border border-primary/20 bg-primary/5 p-4">
                    <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                      <GlobeHemisphereWest size={17} /> Standard transfer
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                      Bank transfers settle via FossaPay; crypto transfers settle directly on-chain.
                    </p>
                  </div>
                  <div className="rounded-card border border-dashed border-primary/15 bg-background p-4 opacity-75">
                    <p className="flex items-center gap-2 text-sm font-medium text-foreground/55">
                      <LockKey size={17} /> Private settlement
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-foreground/50">
                      Private transfers are not available yet.
                    </p>
                  </div>
                </div>
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
                <p className="mt-1 text-xs text-foreground/50">
                  {rate ? 'Live estimate · rate locks for 30 minutes' : rateError ? 'Rate unavailable' : 'Loading live rate…'}
                </p>
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
