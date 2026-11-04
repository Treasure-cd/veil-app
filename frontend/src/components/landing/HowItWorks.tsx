import { motion } from 'framer-motion'
import { Check, Checks, PenNib } from '@phosphor-icons/react'

const ease = [0.22, 1, 0.36, 1] as const

function RequestVisual() {
  return (
    <div className="flex h-full flex-col justify-center gap-3">
      <motion.div
        initial={{ opacity: 0, x: 20, scale: 0.9 }}
        whileInView={{ opacity: 1, x: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ delay: 0.3, type: 'spring', stiffness: 200, damping: 16 }}
        className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-xs text-white"
      >
        Invoice 250 USDC · brand shoot
        <Checks size={14} weight="bold" className="ml-auto mt-1 text-white/70" />
      </motion.div>
      <motion.div
        initial={{ opacity: 0, x: -20, scale: 0.9 }}
        whileInView={{ opacity: 1, x: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ delay: 0.8, type: 'spring', stiffness: 200, damping: 16 }}
        className="max-w-[85%] rounded-2xl rounded-bl-md border border-foreground/10 bg-white px-4 py-2.5 text-xs text-foreground/70"
      >
        Payment link ready. Share it with your customer.
      </motion.div>
    </div>
  )
}

function PayVisual() {
  return (
    <div className="flex h-full items-center justify-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ delay: 0.3, duration: 0.6, ease }}
        className="w-full max-w-[220px] rounded-2xl border border-foreground/10 bg-white p-4 shadow-[0_8px_30px_rgba(46,0,66,0.08)]"
      >
        <div className="mb-3 flex items-center gap-2 text-[11px] text-foreground/50">
          <PenNib size={14} weight="duotone" className="text-primary" />
          Sign payment
        </div>
        <p className="mb-4 font-mono text-lg font-medium text-foreground">250.00 USDC</p>
        <div className="relative">
          <motion.span
            aria-hidden
            className="absolute inset-0 rounded-full bg-primary/40"
            animate={{ scale: [1, 1.25], opacity: [0.6, 0] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: 'easeOut' }}
          />
          <div className="relative rounded-full bg-primary py-2 text-center text-xs font-medium text-white">
            Approve
          </div>
        </div>
      </motion.div>
    </div>
  )
}

function SettleVisual() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2">
      <motion.div
        initial={{ scale: 0, rotate: -90 }}
        whileInView={{ scale: 1, rotate: 0 }}
        viewport={{ once: true }}
        transition={{ delay: 0.4, type: 'spring', stiffness: 260, damping: 14 }}
        className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white"
      >
        <Check size={20} weight="bold" />
      </motion.div>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ delay: 0.7, duration: 0.5, ease }}
        className="font-mono text-2xl font-medium text-foreground"
      >
        ₦385,000
      </motion.p>
      <p className="text-[11px] text-foreground/50">Received in your bank</p>
    </div>
  )
}

const STEPS = [
  {
    n: '01',
    title: 'Request',
    desc: 'Send a text or voice note on WhatsApp, or create a link in the app. Your invoice is ready in seconds.',
    visual: RequestVisual,
  },
  {
    n: '02',
    title: 'Pay',
    desc: 'Your customer opens the link, connects their wallet and signs once. No accounts, no passwords.',
    visual: PayVisual,
  },
  {
    n: '03',
    title: 'Settle',
    desc: 'Dollars go in, naira comes out. Funds land in your local bank account without you touching crypto.',
    visual: SettleVisual,
  },
]

export default function HowItWorks() {
  return (
    <section id="how" className="relative bg-white/50 px-6 py-24 md:px-12 md:py-28">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto mb-16 max-w-xl text-center">
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-4 text-sm font-medium text-primary"
          >
            How it works
          </motion.p>
          <motion.h2
            initial={{ opacity: 0, y: 24, filter: 'blur(8px)' }}
            whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            viewport={{ once: true }}
            transition={{ duration: 0.7, ease }}
            className="text-[clamp(1.9rem,3.5vw,2.75rem)] font-semibold leading-tight tracking-tight"
          >
            Three steps. No hardware.
          </motion.h2>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <motion.div
              key={s.n}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ delay: i * 0.15, duration: 0.7, ease }}
              whileHover={{ y: -6 }}
              className="rounded-3xl border border-foreground/10 bg-white p-4 shadow-[0_2px_24px_rgba(46,0,66,0.05)]"
            >
              <div className="mb-6 h-48 overflow-hidden rounded-2xl bg-primary/5 p-4">
                <s.visual />
              </div>
              <div className="px-3 pb-3">
                <span className="font-mono text-xs text-primary">{s.n}</span>
                <h3 className="mb-2 mt-1 text-xl font-semibold tracking-tight">{s.title}</h3>
                <p className="text-sm leading-relaxed text-foreground/60">{s.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
