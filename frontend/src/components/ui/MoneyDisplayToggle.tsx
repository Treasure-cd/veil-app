import { useDisplayStore } from '../../stores/displayStore'

export function MoneyDisplayToggle({ className = '' }: { className?: string }) {
  const mode = useDisplayStore((state) => state.moneyDisplayMode)
  const setMode = useDisplayStore((state) => state.setMoneyDisplayMode)

  return (
    <div className={`inline-flex items-center rounded-pill border border-primary/10 bg-surface p-0.5 ${className}`} role="group" aria-label="Amount display preference">
      <button
        type="button"
        aria-pressed={mode === 'ngn'}
        onClick={() => setMode('ngn')}
        className={`min-h-7 min-w-7 rounded-pill px-1.5 text-[11px] font-semibold transition-colors sm:min-h-8 sm:min-w-9 sm:px-2.5 sm:text-xs ${mode === 'ngn' ? 'bg-primary-action text-white' : 'text-foreground/55 hover:text-primary'}`}
      >₦</button>
      <button
        type="button"
        aria-pressed={mode === 'token'}
        onClick={() => setMode('token')}
        className={`min-h-7 rounded-pill px-1.5 text-[11px] font-semibold transition-colors sm:min-h-8 sm:px-2.5 sm:text-xs ${mode === 'token' ? 'bg-primary-action text-white' : 'text-foreground/55 hover:text-primary'}`}
      >USDC</button>
    </div>
  )
}
