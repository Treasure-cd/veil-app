import { useEffect, useState } from 'react'
import { ArrowsClockwise, Bank, CheckCircle, Clock, Copy, WarningCircle } from '@phosphor-icons/react'
import { Button } from '../ui/Button'
import { formatNgn } from '../../lib/money'
import { getFiatStatusPresentation, type FiatPayment } from '../../services/fiat'

interface BankTransferCardProps {
  checkout: FiatPayment
  onCheckStatus?: () => void
  checkingStatus?: boolean
  reconcileLabel?: string
  onGenerateNew?: () => void
  generatingNew?: boolean
  canGenerateNew?: boolean
  compact?: boolean
}

function formatCountdown(seconds: number) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, '0')
  const secs = (seconds % 60).toString().padStart(2, '0')
  return `${mins}:${secs}`
}

export function BankTransferCard({
  checkout,
  onCheckStatus,
  checkingStatus = false,
  reconcileLabel,
  onGenerateNew,
  generatingNew = false,
  canGenerateNew = false,
  compact = false,
}: BankTransferCardProps) {
  const [copiedField, setCopiedField] = useState<'account' | 'amount' | null>(null)
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null)

  const isActive = checkout.status === 'pending' || checkout.status === 'processing'
  const payable = checkout.amountPayable ?? checkout.amount

  useEffect(() => {
    if (!checkout.expiresAt || !isActive) {
      setRemainingSeconds(null)
      return
    }
    const update = () => {
      const diff = Math.max(0, Math.ceil((Date.parse(checkout.expiresAt as string) - Date.now()) / 1000))
      setRemainingSeconds(diff)
    }
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [checkout.expiresAt, isActive])

  async function copyValue(value: string | null | undefined, field: 'account' | 'amount') {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopiedField(field)
      window.setTimeout(() => setCopiedField((current) => (current === field ? null : current)), 1800)
    } catch {
      // Clipboard may be unavailable; user can copy manually.
    }
  }

  const badge = getFiatStatusPresentation(checkout.status, checkout.paymentOutcome)
  const isTerminalFailure =
    checkout.status === 'failed' || checkout.status === 'expired' || checkout.status === 'reversed'

  return (
    <div className="rounded-card border border-primary/15 bg-background p-4 text-left sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-primary">
          <Bank size={18} weight="fill" aria-hidden="true" />
          <span>Bank transfer details</span>
        </div>
        <span className={`inline-flex items-center rounded-pill px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
          {badge.label}
        </span>
      </div>

      {isTerminalFailure ? (
        <div className="mt-4 space-y-3">
          <div className="flex items-start gap-2.5 rounded-card border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200">
            <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="space-y-1">
              <p className="font-semibold">
                {checkout.status === 'expired'
                  ? 'This virtual bank account has expired.'
                  : checkout.status === 'reversed'
                    ? 'The transfer was reversed to the sender.'
                    : checkout.paymentOutcome === 'underpaid' || checkout.paymentOutcome === 'overpaid'
                      ? `Transfer ${checkout.paymentOutcome}: expected ${formatNgn(payable)}, received ${formatNgn(checkout.receivedAmount)}.`
                      : 'This bank transfer could not be completed.'}
              </p>
              <p className="text-amber-800/80 dark:text-amber-200/80">
                Do not transfer funds to this account number.
              </p>
            </div>
          </div>
          {canGenerateNew && onGenerateNew && (
            <Button
              size="md"
              fullWidth
              loading={generatingNew}
              onClick={onGenerateNew}
            >
              Generate new transfer account
            </Button>
          )}
          {onCheckStatus && (
            <Button
              size="md"
              variant="secondary"
              fullWidth
              loading={checkingStatus}
              leftIcon={<ArrowsClockwise size={16} />}
              onClick={onCheckStatus}
            >
              Reconcile status
            </Button>
          )}
        </div>
      ) : (
        <>
          <div className="mt-4 rounded-card border border-primary/10 bg-surface p-3.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-foreground/55">Exact amount to send</p>
                <p className="mt-0.5 font-mono text-2xl font-semibold tabular-nums text-primary">
                  {formatNgn(payable)}
                </p>
                {checkout.fee && Number(checkout.fee) > 0 && checkout.feeBearer === 'customer' && (
                  <p className="mt-0.5 text-xs text-foreground/50">
                    Includes {formatNgn(checkout.fee)} transfer fee
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => void copyValue(payable, 'amount')}
                className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-sm border border-primary/15 bg-background px-3 text-xs font-medium text-primary transition hover:border-primary/35 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {copiedField === 'amount' ? <CheckCircle size={15} weight="fill" /> : <Copy size={15} />}
                {copiedField === 'amount' ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>

          <dl className="mt-3 space-y-2.5 rounded-card border border-primary/10 bg-surface p-3.5 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-foreground/55">Bank</dt>
              <dd className="font-medium text-foreground">{checkout.bankName || '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-primary/5 pt-2.5">
              <dt className="text-foreground/55">Account number</dt>
              <dd className="flex items-center gap-2">
                <span className="font-mono text-base font-semibold tabular-nums text-primary">
                  {checkout.accountNumber || '—'}
                </span>
                {checkout.accountNumber && (
                  <button
                    type="button"
                    aria-label="Copy account number"
                    onClick={() => void copyValue(checkout.accountNumber, 'account')}
                    className="inline-flex size-8 items-center justify-center rounded-sm border border-primary/15 text-primary transition hover:border-primary/35 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {copiedField === 'account' ? <CheckCircle size={15} weight="fill" /> : <Copy size={15} />}
                  </button>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-primary/5 pt-2.5">
              <dt className="text-foreground/55">Account name</dt>
              <dd className="truncate font-medium text-foreground" title={checkout.accountName || undefined}>
                {checkout.accountName || '—'}
              </dd>
            </div>
          </dl>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-foreground/60">
            <span className="inline-flex items-center gap-1.5">
              <Clock size={14} aria-hidden="true" />
              {remainingSeconds !== null
                ? remainingSeconds > 0
                  ? <span className="tabular-nums">Expires in {formatCountdown(remainingSeconds)}</span>
                  : 'Account expiring…'
                : '30-minute single-use account'}
            </span>
            <span className="font-mono text-[11px] text-foreground/45">{checkout.reference}</span>
          </div>

          {!compact && (
            <p className="mt-3 rounded-card bg-primary/[0.04] px-3 py-2 text-xs leading-relaxed text-foreground/65">
              Transfer the exact amount in one single bank transfer. Partial or split payments are rejected.
            </p>
          )}

          {isActive && onCheckStatus && (
            <Button
              className="mt-4"
              size="lg"
              fullWidth
              loading={checkingStatus}
              leftIcon={<ArrowsClockwise size={18} />}
              onClick={onCheckStatus}
            >
              {reconcileLabel ?? 'I’ve sent the transfer'}
            </Button>
          )}
        </>
      )}
    </div>
  )
}
