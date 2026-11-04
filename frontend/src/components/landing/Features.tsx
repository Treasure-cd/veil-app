import { motion } from 'framer-motion'
import { ChatCircleText, EyeSlash, DeviceMobile, LockKey, ClockCounterClockwise } from '@phosphor-icons/react'
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
              desc="Lock funds in a vault, hide individual salaries, and execute bulk multi-recipient payouts automatically via CSV."
            />
            <div className="mt-8 rounded-2xl bg-primary/5 p-5">
              <div className="mb-3 flex items-end justify-between">
                <div>
                  <p className="text-[11px] text-foreground/50">Payroll vault locked</p>
                  <p className="font-mono text-2xl font-medium">4,350 USDC</p>
                </div>
                <span className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-primary shadow-sm">
                  Scheduled for Friday
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
              desc="Text the bot. Get a secure checkout link instantly."
            />
            <div className="mt-8 space-y-2">
              <div className="ml-auto w-fit rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-xs text-white">
                invoice 30k for waistbeads
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

          {/* Replaced Settlement with Hardware-Free POS to match the new pitch */}
          <SpotlightCard className="md:col-span-3">
            <CardHeader
              icon={DeviceMobile}
              title="Hardware-Free POS"
              desc="Your phone is the terminal. Track volume, scan QR codes, and view complete transaction history without buying physical hardware."
            />
            <div className="mt-8 flex flex-col gap-2 rounded-xl bg-white p-3 shadow-sm border border-foreground/5">
              <div className="flex items-center justify-between border-b border-foreground/5 pb-2">
                <div className="flex items-center gap-2">
                  <div className="h-6 w-6 rounded-full bg-green-100 flex items-center justify-center text-green-600">
                    <ClockCounterClockwise size={12} weight="bold" />
                  </div>
                  <span className="text-xs font-medium text-foreground">Recent Volume</span>
                </div>
                <span className="font-mono text-sm font-semibold">1,250 USDC</span>
              </div>
              <div className="flex justify-between text-[10px] text-foreground/50 pt-1">
                <span>Total Transactions</span>
                <span>48 this week</span>
              </div>
            </div>
          </SpotlightCard>

          {/* Private */}
          <SpotlightCard className="md:col-span-3">
            <CardHeader
              icon={EyeSlash}
              title="Private by default"
              desc="Powered by Umbra, exact transaction amounts and wallet histories remain invisible on the blockchain."
            />
            <div className="mt-8 flex h-16 items-center rounded-xl bg-primary/5 px-4">
              <motion.p
                animate={{ filter: ['blur(0px)', 'blur(8px)', 'blur(8px)', 'blur(0px)'] }}
                transition={{ duration: 4, repeat: Infinity, times: [0, 0.35, 0.7, 1] }}
                className="font-mono text-3xl font-semibold text-foreground tracking-tight"
              >
                18.50 USDC
              </motion.p>
            </div>
          </SpotlightCard>
        </div>
      </div>
    </section>
  )
}
