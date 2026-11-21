import { useState } from 'react'
import { X } from '@phosphor-icons/react'
import { NETWORK } from '../../lib/network'

const DISMISSED_KEY = 'veil-devnet-notice-dismissed'

export function DevnetNotice({ className = '' }: { className?: string }) {
  const [dismissed, setDismissed] = useState(() => {
    try { return window.localStorage.getItem(DISMISSED_KEY) === 'true' } catch { return false }
  })

  if (NETWORK !== 'devnet' || dismissed) return null

  function dismiss() {
    try { window.localStorage.setItem(DISMISSED_KEY, 'true') } catch { /* storage may be disabled */ }
    setDismissed(true)
  }

  return (
    <aside className={`flex items-center justify-between gap-3 border-b border-amber-200/80 bg-amber-50 px-4 py-2.5 text-xs text-amber-950 sm:px-6 ${className}`} role="status">
      <p className="min-w-0 leading-relaxed">
        <span className="font-semibold">Devnet:</span> test tokens have no real value. Get test SOL from the{' '}
        <a href="https://faucet.solana.com" target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2 hover:text-amber-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">Solana faucet</a>.
      </p>
      <button type="button" onClick={dismiss} aria-label="Dismiss devnet notice" className="flex size-8 shrink-0 items-center justify-center rounded-pill text-amber-900/70 transition-colors hover:bg-amber-100 hover:text-amber-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <X size={16} weight="bold" />
      </button>
    </aside>
  )
}
