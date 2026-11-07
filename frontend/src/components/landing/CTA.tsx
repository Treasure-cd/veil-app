import { Link } from 'react-router'
import { motion } from 'framer-motion'
import { ArrowRight } from '@phosphor-icons/react'

const ease = [0.22, 1, 0.36, 1] as const

export default function CTA() {
  return (
    <section className="relative isolate">
      <motion.div
        initial={{ opacity: 0, y: 48 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: '-80px' }}
        transition={{ duration: 0.9, ease }}
        className="relative w-full overflow-hidden bg-secondary px-6 py-24 text-center md:px-12"
        style={{
          backgroundImage: 'radial-gradient(rgba(255,255,255,0.09) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      >
        <motion.div
          aria-hidden
          className="absolute -left-20 -top-20 h-80 w-80 rounded-full bg-primary/60 blur-3xl"
          animate={{ x: [0, 50, 0], y: [0, 30, 0] }}
          transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.div
          aria-hidden
          className="absolute -bottom-24 -right-16 h-80 w-80 rounded-full bg-accent/50 blur-3xl"
          animate={{ x: [0, -40, 0], y: [0, -40, 0] }}
          transition={{ duration: 14, repeat: Infinity, ease: 'easeInOut' }}
        />

        <div className="relative mx-auto max-w-6xl">
          <motion.p
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
            className="mb-5 text-sm font-medium text-white/60"
          >
            Try the MVP
          </motion.p>

          <motion.h2
            initial={{ opacity: 0, y: 24, filter: 'blur(8px)' }}
            whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            viewport={{ once: true }}
            transition={{ delay: 0.3, duration: 0.8, ease }}
            className="mx-auto mb-5 max-w-2xl text-[clamp(2rem,4.5vw,3.5rem)] font-semibold leading-[1.05] tracking-tight text-white"
          >
            Your next checkout is one message away.
          </motion.h2>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.45, duration: 0.6, ease }}
            className="mx-auto mb-10 max-w-[42ch] text-base text-white/60"
          >
            Connect a wallet, generate your first secure link, and get paid instantly in stablecoins. Zero hardware required.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.6, duration: 0.6, ease }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.96 }}
            className="inline-block"
          >
            <Link
              to="/app"
              className="inline-flex h-14 items-center gap-2 rounded-lg bg-white px-9 text-sm font-semibold text-secondary shadow-[0_0_60px_rgba(255,255,255,0.25)]"
            >
              Launch App
              <ArrowRight weight="bold" size={16} />
            </Link>
          </motion.div>
        </div>
      </motion.div>
    </section>
  )
}
