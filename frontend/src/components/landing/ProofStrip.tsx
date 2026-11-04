import { motion } from 'framer-motion'
import { Lightning, LockKey, WhatsappLogo, DeviceMobile } from '@phosphor-icons/react'

const ease = [0.22, 1, 0.36, 1] as const

const FACTS = [
  { icon: Lightning, title: 'Instant Settlement', sub: 'Lightning-fast on Solana' },
  { icon: LockKey, title: 'Confidential by Default', sub: 'Shielded via Umbra' },
  { icon: WhatsappLogo, title: 'WhatsApp Native', sub: 'Bot-generated checkouts' },
  { icon: DeviceMobile, title: 'Hardware-Free POS', sub: 'Your phone is the terminal' },
]


const BUILT_WITH = ['Solana', 'Umbra', 'Next.js', 'WhatsApp', 'Phantom', 'Solflare']

export default function ProofStrip() {
  return (
    <section className="relative border-y border-foreground/5 bg-white/60 py-14 backdrop-blur">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 px-6 md:grid-cols-4">
        {FACTS.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-60px' }}
            transition={{ delay: i * 0.1, duration: 0.6, ease }}
            whileHover={{ y: -4 }}
            className="flex flex-col items-center gap-3 text-center"
          >
            <motion.span
              whileHover={{ rotate: -8, scale: 1.1 }}
              className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary"
            >
              <f.icon size={22} weight="duotone" />
            </motion.span>
            <div>
              <p className="text-sm font-medium text-foreground">{f.title}</p>
              <p className="text-xs text-foreground/50">{f.sub}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* marquee */}
      <div className="relative mx-auto mt-12 max-w-4xl overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_15%,black_85%,transparent)]">
        <motion.div
          className="flex w-max gap-14"
          animate={{ x: ['0%', '-50%'] }}
          transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
        >
          {[...BUILT_WITH, ...BUILT_WITH].map((name, i) => (
            <span
              key={i}
              className="text-lg font-semibold tracking-tight text-foreground/30 transition-colors hover:text-primary"
            >
              {name}
            </span>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
