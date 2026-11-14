import { motion } from 'framer-motion'
import { LockKey } from '@phosphor-icons/react'
import WhatsappMockup from './WhatsappMockup'

const ease = [0.22, 1, 0.36, 1] as const

const HEADLINE = ['Turn', 'chats', 'into', 'checkouts.']

const word = {
  hidden: { opacity: 0, y: 28, filter: 'blur(10px)' },
  show: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.7, ease },
  },
}

function LightField() {
  return (
    <motion.div
      aria-hidden="true"
      className="pointer-events-none absolute inset-[-50%] z-0"
      animate={{ rotate: 360 }}
      transition={{
        duration: 60,
        repeat: Infinity,
        ease: 'linear',
      }}
      style={{
        background: `
          conic-gradient(
            from 180deg at 50% 50%,
            transparent 0deg,
            rgba(92, 4, 159, 0.18) 60deg,
            transparent 120deg,
            rgba(72, 6, 254, 0.15) 200deg,
            transparent 260deg,
            rgba(92, 4, 159, 0.14) 320deg,
            transparent 360deg
          )
        `,
        filter: 'blur(70px)',
      }}
    />
  )
}


function NoiseOverlay() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-10 opacity-35 mix-blend-multiply"
      style={{
        backgroundImage: `url("data:image/svg+xml,%3Csvg width='200' height='200' viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
        backgroundSize: '180px 180px',
      }}
    />
  )
}

function Vignette() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-[1]"
      style={{
        background: `
          radial-gradient(
            ellipse at center,
            transparent 30%,
            rgba(33, 8, 30, 0.25) 100%
          )
        `,
      }}
    />
  )
}

export default function Hero() {
  return (
    <section className="relative flex min-h-screen items-center overflow-hidden bg-[size:24px_24px] pt-24">

      {/* Ambient anamorphic light field */}
      <LightField />

      {/* Primary ambient glow */}
      <motion.div
        aria-hidden="true"
        className="pointer-events-none absolute -left-[10vw] top-0 h-[45vw] w-[45vw] max-h-[700px] max-w-[700px] rounded-full bg-primary/20 blur-3xl"
        animate={{ x: [0, 60, 0], y: [0, 40, 0] }}
        transition={{
          duration: 14,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      {/* Secondary ambient glow */}
      <motion.div
        aria-hidden="true"
        className="pointer-events-none absolute -right-[10vw] bottom-0 h-[45vw] w-[45vw] max-h-[700px] max-w-[700px] rounded-full bg-accent/20 blur-3xl"
        animate={{ x: [0, -50, 0], y: [0, -50, 0] }}
        transition={{
          duration: 16,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      {/* Edge vignette */}
      <Vignette />

      {/* Cryptographic film grain */}
      <NoiseOverlay />

      {/* Hero content */}
      <div className="relative z-20 flex w-full flex-wrap items-center justify-between gap-16 px-6 py-20 md:px-12 lg:px-20">

        {/* Copy */}
        <div className="min-w-0 flex-1 basis-80">

          <motion.h1
            initial="hidden"
            animate="show"
            transition={{
              staggerChildren: 0.09,
              delayChildren: 0.2,
            }}
            className="mb-6 text-[clamp(2.4rem,5vw,4rem)] font-semibold leading-[1.05] tracking-tight text-foreground"
          >
            {HEADLINE.map((w, i) => (
              <motion.span
                key={i}
                variants={word}
                className={`mr-[0.25em] inline-block ${
                  i === HEADLINE.length - 1
                    ? 'bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent'
                    : ''
                }`}
              >
                {w}
              </motion.span>
            ))}
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.75, duration: 0.6, ease }}
            className="mb-9 max-w-[42ch] text-base leading-relaxed text-foreground/70"
          >
            Generate secure payment links directly from WhatsApp. Your
            customers pay instantly in stablecoins, and your business
            finances stay completely private.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.9, duration: 0.6, ease }}
            className="flex flex-wrap items-center gap-4"
          >
            <div
              aria-disabled="true"
              className="inline-flex h-12 cursor-default items-center gap-2 rounded-lg bg-primary px-7 text-sm font-medium text-white opacity-60 shadow-[0_8px_28px_rgba(92,4,159,0.35)]"
            >
              Coming soon
            </div>

            <motion.a
              href="#how"
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              className="inline-flex h-12 items-center gap-2 rounded-full px-6 text-sm font-medium text-foreground/70 transition-colors hover:text-foreground"
            >
              See the demo
            </motion.a>
          </motion.div>
        </div>

        {/* WhatsApp mockup */}
        <motion.div
          initial={{ opacity: 0, x: 60, rotate: 3 }}
          animate={{ opacity: 1, x: 0, rotate: 0 }}
          transition={{ delay: 0.3, duration: 0.9, ease }}
          className="relative shrink-0"
        >
          <motion.div
            animate={{ y: [0, -12, 0] }}
            transition={{
              duration: 6,
              repeat: Infinity,
              ease: 'easeInOut',
            }}
          >
            <WhatsappMockup />
          </motion.div>

          {/* Settlement badge */}
          <motion.div
            initial={{ opacity: 0, scale: 0.6, x: -20 }}
            animate={{ opacity: 1, scale: 1, x: 0 }}
            transition={{
              delay: 1.3,
              type: 'spring',
              stiffness: 200,
              damping: 14,
            }}
            className="absolute -left-8 bottom-24 rounded-2xl border border-foreground/10 bg-white/90 px-4 py-3 shadow-[0_12px_40px_rgba(46,0,66,0.15)] backdrop-blur"
          >
            <p className="text-[10px] text-foreground/50">
              Instant Settlement
            </p>
            <p className="font-mono text-sm font-medium text-foreground">
              18.50 USDC
            </p>
          </motion.div>

          {/* Privacy badge */}
          <motion.div
            initial={{ opacity: 0, scale: 0.6, x: 20 }}
            animate={{ opacity: 1, scale: 1, x: 0 }}
            transition={{
              delay: 1.6,
              type: 'spring',
              stiffness: 200,
              damping: 14,
            }}
            className="absolute -right-6 top-20 flex items-center gap-2 rounded-full border border-primary/20 bg-white/90 px-3.5 py-2 text-xs font-medium text-primary shadow-[0_12px_40px_rgba(46,0,66,0.15)] backdrop-blur"
          >
            <LockKey weight="fill" size={14} />
            Data Shielded
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}
