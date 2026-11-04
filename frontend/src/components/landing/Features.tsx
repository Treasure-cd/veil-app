import { motion } from 'framer-motion'
import { ChatCircleText, EyeSlash, Lightning, LockKey, ArrowRight } from '@phosphor-icons/react'
import SpotlightCard from './SpotlightCard'

const ease = [0.22, 1, 0.36, 1] as const

function CardHeader({
  icon: Icon,
  title,
  desc,
}: {
  icon: typeof LockKey
  title: string
  desc: string
}) {
  return (
    <>
      <motion.span
        whileHover={{ rotate: -10, scale: 1.1 }}
        className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary"
      >
        <Icon size={22} weight="duotone" />
      </motion.span>
      <h3 className="mb-2 text-xl font-semibold tracking-tight">{title}</h3>
      <p className="max-w-[40ch] text-sm leading-relaxed text-foreground/60">{desc}</p>
    </>
  )
}

export default function Features() {
  return (
    <section className="relative bg-primary/[0.025] px-6 py-24 md:px-12 md:py-28">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto mb-16 max-w-xl text-center">
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-4 text-sm font-medium text-primary"
          >
            Everything in one place
          </motion.p>
          <motion.h2
            initial={{ opacity: 0, y: 24, filter: 'blur(8px)' }}
            whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            viewport={{ once: true }}
            transition={{ duration: 0.7, ease }}
            className="text-[clamp(1.9rem,3.5vw,2.75rem)] font-semibold leading-tight tracking-tight"
          >
            Built for how you actually get paid.
          </motion.h2>
        </div>

        <div className="grid gap-5 md:grid-cols-6">
          {/* Payroll */}
          <SpotlightCard className="md:col-span-4">
            <CardHeader
              icon={LockKey}
              title="Confidential payroll"
              desc="Lock funds in a vault, hide individual salaries, and release automatically on schedule."
            />
            <div className="mt-8 rounded-2xl bg-primary/5 p-5">
              <div className="mb-3 flex items-end justify-between">
                <div>
                  <p className="text-[11px] text-foreground/50">Vault locked</p>
                  <p className="font-mono text-2xl font-medium">4,350 USDC</p>
                </div>
                <span className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-primary">
                  Scheduled
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-primary/10">
                <motion.div
                  initial={{ width: 0 }}
                  whileInView={{ width: '100%' }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.4, duration: 1.6, ease }}
                  className="h-full rounded-full bg-gradient-to-r from-primary to-accent"
                />
              </div>
            </div>
          </SpotlightCard>

          {/* WhatsApp */}
          <SpotlightCard className="md:col-span-2">
            <CardHeader
              icon={ChatCircleText}
              title="WhatsApp invoicing"
              desc="Text or voice note in, payment link out."
            />
            <div className="mt-8 space-y-2">
              <div className="ml-auto w-fit rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-xs text-white">
                invoice Tunde 150 usdc
              </div>
              <div className="flex w-fit items-center gap-1 rounded-2xl rounded-bl-md bg-primary/5 px-3.5 py-3">
                {[0, 1, 2].map((d) => (
                  <motion.span
                    key={d}
                    className="h-1.5 w-1.5 rounded-full bg-primary/60"
                    animate={{ y: [0, -4, 0] }}
                    transition={{ duration: 0.9, repeat: Infinity, delay: d * 0.15 }}
                  />
                ))}
              </div>
            </div>
          </SpotlightCard>

          {/* Settlement */}
          <SpotlightCard className="md:col-span-3">
            <CardHeader
              icon={Lightning}
              title="Instant settlement"
              desc="Automatic off-ramp to local bank accounts through Pajramp."
            />
            <div className="mt-8 flex items-center gap-3">
              <span className="rounded-full bg-primary/10 px-4 py-2 font-mono text-sm text-primary">
                USDC
              </span>
              <motion.span
                animate={{ x: [0, 8, 0] }}
                transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
                className="text-foreground/40"
              >
                <ArrowRight size={18} weight="bold" />
              </motion.span>
              <span className="rounded-full bg-accent/10 px-4 py-2 font-mono text-sm text-accent">
                NGN
              </span>
            </div>
          </SpotlightCard>

          {/* Private */}
          <SpotlightCard className="md:col-span-3">
            <CardHeader
              icon={EyeSlash}
              title="Private by default"
              desc="Amounts and recipients stay between the people involved."
            />
            <div className="mt-8">
              <motion.p
                animate={{ filter: ['blur(0px)', 'blur(7px)', 'blur(7px)', 'blur(0px)'] }}
                transition={{ duration: 4, repeat: Infinity, times: [0, 0.35, 0.7, 1] }}
                className="font-mono text-2xl font-medium"
              >
                250.00 USDC
              </motion.p>
            </div>
          </SpotlightCard>
        </div>
      </div>
    </section>
  )
}
