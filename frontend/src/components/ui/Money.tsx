import { formatNgn, formatTokenAmount } from '../../lib/money'
import { useDisplayStore } from '../../stores/displayStore'

interface MoneyProps {
  amountNgn?: string | number | null
  tokenAmount?: string | number | null
  token?: string
  className?: string
  primaryClassName?: string
  secondaryClassName?: string
  align?: 'left' | 'right'
}

export function Money({
  amountNgn,
  tokenAmount,
  token,
  className = '',
  primaryClassName = '',
  secondaryClassName = '',
  align = 'left',
}: MoneyProps) {
  const displayMode = useDisplayStore((state) => state.moneyDisplayMode)
  const hasNgn = amountNgn !== null && amountNgn !== undefined && amountNgn !== ''
  const ngnPrimary = (displayMode === 'ngn' && hasNgn) || tokenAmount == null || !token
  const primary = ngnPrimary ? formatNgn(amountNgn) : `${formatTokenAmount(tokenAmount)} ${token}`
  const secondary = ngnPrimary
    ? token && tokenAmount != null ? `≈ ${formatTokenAmount(tokenAmount)} ${token}` : null
    : amountNgn != null ? `≈ ${formatNgn(amountNgn)}` : null

  return (
    <span className={`inline-flex min-w-0 flex-col ${align === 'right' ? 'items-end text-right' : 'items-start'} ${className}`}>
      <span className={`font-mono tabular-nums ${primaryClassName}`}>{primary}</span>
      {secondary && <span className={`mt-0.5 text-xs font-normal text-foreground/50 ${secondaryClassName}`}>{secondary}</span>}
    </span>
  )
}
