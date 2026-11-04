import { useState } from 'react'
import { Link } from 'react-router'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle, Lock } from '@phosphor-icons/react'

const ease = [0.22, 1, 0.36, 1] as const

const ROWS = [
  { name: 'Ada O.', amount: '1,200.00' },
  { name: 'Tunde B.', amount: '950.00' },
  { name: 'Chioma E.', amount: '1,400.00' },
  { name: 'Emeka N.', amount: '800.00' },
]

const POINTS = [
  'Fund once, lock it in a vault',
  'Individual salaries stay hidden',
  'Releases automatically on schedule',
]

type View = 'employer' | 'public'

export default function PayrollSpotlight() {
  const [view, setView] = useState<View>('employer')

  return (
    <section id="payroll" className="relative bg-white/50 px-6 py-24 md:px-12 md:py-28">
      <div className="mx-auto grid max-w-6xl items-center gap-16 md:grid-cols-2">
        {/* copy */}
        <div>
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-4 text-sm font-medium text-primary"
          >
            Confidential payroll
          </motion.p>
          <motion.h2
            initial={{ opacity: 0, y: 24, filter: 'blur(8px)' }}
            whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            viewport={{ once: true }}
            transition={{ duration: 0.7, ease }}
            className="mb-6 text-[clamp(1.9rem,3.5vw,2.75rem)] font-semibold leading-tight tracking-tight"
          >
            Pay your team. Keep the numbers private.
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1, duration: 0.6, ease }}
            className="mb-8 max-w-[44ch] text-base leading-relaxed text-foreground/60"
          >
            Cross-border payroll shouldn't mean everyone seeing what everyone earns. Veil
            holds the funds, hides the amounts, and pays out on the day you choose.
          </motion.p>

          <ul className="mb-10 space-y-4">
            {POINTS.map((p, i) => (
              <motion.li
                key={p}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.2 + i * 0.12, duration: 0.5, ease }}
                className="flex items-center gap-3 text-sm text-foreground/80"
              >
                <CheckCircle size={22} weight="fill" className="text-primary" />
                {p}
              </motion.li>
            ))}
          </ul>

          <motion.div whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} className="w-fit">
            <Link
              to="/app"
              className="inline-flex h-12 items-center rounded-full bg-primary px-7 text-sm font-medium text-white shadow-[0_8px_28px_rgba(92,4,159,0.35)]"
            >
              Run a payroll
            </Link>
          </motion.div>
        </div>

        {/* mock table */}
        <motion.div
          initial={{ opacity: 0, y: 40, rotate: 1.5 }}
          whileInView={{ opacity: 1, y: 0, rotate: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.8, ease }}
          className="relative"
        >
          <div className="absolute -inset-6 -z-10 rounded-[2.5rem] bg-gradient-to-br from-primary/15 to-accent/15 blur-2xl" />

          <div className="rounded-3xl border border-foreground/10 bg-white p-6 shadow-[0_20px_60px_rgba(46,0,66,0.12)]">
            {/* header row */}
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[11px] text-foreground/50">Payroll vault</p>
                <p className="flex items-center gap-2 font-mono text-xl font-medium">
                  <Lock size={18} weight="fill" className="text-primary" />
                  4,350.00 USDC
                </p>
              </div>

              <div className="relative flex rounded-full bg-primary/5 p-1 text-xs font-medium">
                {(['employer', 'public'] as View[]).map((v) => (
                  <button
                    key={v}
                    onClick={() => setView(v)}
                    className={`relative z-10 rounded-full px-4 py-1.5 capitalize transition-colors ${
                      view === v ? 'text-white' : 'text-foreground/60'
                    }`}
                  >
                    {view === v && (
                      <motion.span
                        layoutId="payroll-toggle"
                        className="absolute inset-0 -z-10 rounded-full bg-primary"
                        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                      />
                    )}
                    {v}
                  </button>
                ))}
              </div>
            </div>

            {/* rows */}
            <div className="divide-y divide-foreground/5">
              {ROWS.map((r, i) => (
                <motion.div
                  key={r.name}
                  initial={{ opacity: 0, x: 24 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.3 + i * 0.1, duration: 0.5, ease }}
                  className="flex items-center justify-between py-3.5"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      {r.name[0]}
                    </span>
                    <span className="text-sm">{r.name}</span>
                  </div>

                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                      key={view}
                      initial={{ opacity: 0, filter: 'blur(6px)' }}
                      animate={{ opacity: 1, filter: 'blur(0px)' }}
                      exit={{ opacity: 0, filter: 'blur(6px)' }}
                      transition={{ duration: 0.2 }}
                      className="font-mono text-sm"
                    >
                      {view === 'employer' ? `${r.amount} USDC` : '••••••'}
                    </motion.span>
                  </AnimatePresence>
                </motion.div>
              ))}
            </div>

            {/* footer */}
            <div className="mt-5 flex items-center justify-between rounded-2xl bg-primary/5 px-4 py-3 text-xs">
              <span className="text-foreground/60">Releases Friday, 09:00</span>
              <span className="flex items-center gap-1.5 font-medium text-primary">
                <motion.span
                  className="h-1.5 w-1.5 rounded-full bg-primary"
                  animate={{ opacity: [1, 0.3, 1] }}
                  transition={{ duration: 1.6, repeat: Infinity }}
                />
                Scheduled
              </span>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
