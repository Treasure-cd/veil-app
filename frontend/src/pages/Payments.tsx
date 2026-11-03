import { useState } from 'react'
import {
  CheckCircle,
  Copy,
  GlobeHemisphereWest,
  Link as LinkIcon,
  LockKey,
} from '@phosphor-icons/react'
import { Button } from '../components/ui/Button'
import { useAuth } from '../auth/useAuth'
import { api } from '../services/api'

type Token = 'USDC' | 'SOL'

const TOKEN_CONFIG: Record<Token, { decimals: number; mint: string }> = {
  USDC: { decimals: 6, mint: '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU' },
  SOL: { decimals: 9, mint: 'So11111111111111111111111111111111111111112' },
}

interface PaymentIntent {
  id: string
}

function toAtomicAmount(value: string, decimals: number): string | null {
  if (!/^\d+(?:\.\d*)?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  if (fraction.length > decimals) return null
  const atomic = BigInt(whole) * 10n ** BigInt(decimals) +
    BigInt(fraction.padEnd(decimals, '0') || '0')
  return atomic > 0n ? atomic.toString() : null
}

export default function Payments() {
  const { user } = useAuth()
  const [amount, setAmount] = useState('')
  const [token, setToken] = useState<Token>('USDC')
  const [memo, setMemo] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [generatedLink, setGeneratedLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function handleGenerate() {
    setError(null)
    const amountAtomic = toAtomicAmount(amount, TOKEN_CONFIG[token].decimals)
    if (!amountAtomic) {
      setError(`Enter a positive amount with up to ${TOKEN_CONFIG[token].decimals} decimal places.`)
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
          mint: TOKEN_CONFIG[token].mint,
          amountAtomic,
          recipientAddress: user.address,
          receiveMode: 'public',
          memo: memo.trim() || 'Payment request',
        }),
      })
      if (!intent.id) throw new Error('The payment request was created without an ID.')
      setGeneratedLink(new URL(`/pay/${intent.id}`, window.location.origin).toString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the payment request.')
    } finally {
      setIsLoading(false)
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

  if (generatedLink) {
    return (
      <div className="mx-auto max-w-2xl">
        <section className="rounded-panel border border-primary/10 bg-white p-6 text-center shadow-veil-sm sm:p-8">
          <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
            <CheckCircle size={30} weight="fill" />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-primary">Payment link ready</h1>
          <p className="mx-auto mt-2 max-w-md text-sm text-foreground/65">
            Share this checkout link. Your customer does not need a Veil account, but will need to connect a Solana wallet.
          </p>
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
          {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
          <Button
            className="mt-6"
            variant="secondary"
            onClick={() => {
              setGeneratedLink(null)
              setAmount('')
              setMemo('')
              setError(null)
            }}
          >
            Create another request
          </Button>
        </section>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-primary">Request payment</h1>
        <p className="mt-1 text-sm text-foreground/70">Create a checkout link that customers can pay with a connected Solana wallet.</p>
      </header>

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
              <label htmlFor="payment-amount" className="text-sm font-medium">Amount</label>
              <input
                id="payment-amount"
                type="number"
                min="0"
                step="any"
                inputMode="decimal"
                placeholder="0.00"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
              />
            </div>
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Currency</legend>
              <div className="flex h-11 rounded-card bg-primary/5 p-1">
                {(['USDC', 'SOL'] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={token === option}
                    onClick={() => setToken(option)}
                    className={`flex-1 rounded-md text-sm font-medium transition-colors ${
                      token === option
                        ? 'bg-white text-primary shadow-veil-sm'
                        : 'text-foreground/60 hover:text-foreground'
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>

          <div className="border-t border-primary/10 pt-5">
            <p className="text-sm font-medium">Settlement</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div className="rounded-card border border-primary/20 bg-primary/5 p-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                  <GlobeHemisphereWest size={17} /> Standard transfer
                </p>
                <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                  Settled as a regular on-chain transfer. Transaction details are visible on the blockchain.
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
            <p className="my-2 break-all text-4xl font-semibold tracking-tight text-primary">
              {amount || '0.00'} <span className="text-2xl text-primary/60">{token}</span>
            </p>
            <p className="max-w-full break-words text-sm text-foreground/70">{memo.trim() || 'Payment request'}</p>
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
    </div>
  )
}
