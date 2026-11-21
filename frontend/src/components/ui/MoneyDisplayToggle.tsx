import { useDisplayStore } from '../../stores/displayStore'

export function MoneyDisplayToggle({ className = '' }: { className?: string }) {
  const mode = useDisplayStore((state) => state.moneyDisplayMode)
  const setMode = useDisplayStore((state) => state.setMoneyDisplayMode)

  return (
    <div className={`inline-flex items-center rounded-pill border border-primary/10 bg-white p-0.5 ${className}`} role="group" aria-label="Amount display preference">
      <button
        type="button"
        aria-pressed={mode === 'ngn'}
        onClick={() => setMode('ngn')}
        className={`min-h-8 min-w-9 rounded-pill px-2.5 text-xs font-semibold transition-colors ${mode === 'ngn' ? 'bg-primary text-white' : 'text-foreground/55 hover:text-primary'}`}
      >₦</button>
      <button
        type="button"
        aria-pressed={mode === 'token'}
        onClick={() => setMode('token')}
        className={`min-h-8 rounded-pill px-2.5 text-xs font-semibold transition-colors ${mode === 'token' ? 'bg-primary text-white' : 'text-foreground/55 hover:text-primary'}`}
      >USDC</button>
    </div>
  )
}
