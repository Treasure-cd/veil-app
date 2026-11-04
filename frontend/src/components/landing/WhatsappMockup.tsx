import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Checks,
  PaperPlaneRight,
  Microphone,
  CheckCircle,
  LockKey,
} from '@phosphor-icons/react'
import Logo from './Logo'

// Changed user kind to text so it's readable immediately without them having to guess what a voice note says
type Msg =
  | { id: number; from: 'user'; kind: 'text'; text: string; time: string }
  | { id: number; from: 'bot'; kind: 'invoice'; time: string }
  | { id: number; from: 'bot'; kind: 'text'; text: string; time: string }
  | { id: number; from: 'bot'; kind: 'settled'; time: string }

const MESSAGES: Msg[] = [
  { id: 1, from: 'user', kind: 'text', text: 'Invoice 30k for custom waistbeads', time: '09:41' },
  { id: 2, from: 'bot', kind: 'invoice', time: '09:41' },
  { id: 3, from: 'bot', kind: 'text', text: 'Payment received. Wallet address kept private.', time: '09:43' },
  { id: 4, from: 'bot', kind: 'settled', time: '09:43' },
]

const bubbleIn = {
  initial: { opacity: 0, y: 14, scale: 0.92 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, transition: { duration: 0.2 } },
  transition: { type: 'spring', stiffness: 260, damping: 22 },
} as const

function Time({ t, user }: { t: string; user?: boolean }) {
  return (
    <span className="mt-1 flex items-center justify-end gap-1 text-[8.5px] leading-none text-foreground/40">
      {t}
      {user && <Checks size={11} weight="bold" className="text-accent" />}
    </span>
  )
}

function Bubble({ msg }: { msg: Msg }) {
  const isUser = msg.from === 'user'

  return (
    <motion.div
      layout
      {...bubbleIn}
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[82%] px-3 pb-1.5 pt-2 text-[11.5px] leading-relaxed text-foreground shadow-[0_1px_2px_rgba(46,0,66,0.12)] ${
          isUser
            ? 'rounded-[14px_3px_14px_14px] bg-[#ecdcfa]'
            : 'rounded-[3px_14px_14px_14px] bg-white'
        }`}
      >
        {msg.from === 'user' && msg.kind === 'text' && (
          <p>{msg.text}</p>
        )}

        {msg.kind === 'invoice' && (
          <div className="min-w-[170px]">
            <p className="mb-1.5 font-medium">Invoice generated</p>
            <div className="mb-1.5 rounded-lg bg-primary/5 p-2">
              <p className="font-mono text-sm font-medium">₦30,000</p>
              <p className="text-[10px] text-foreground/50">Custom waistbeads</p>
            </div>
            <p className="font-mono text-[10px] text-primary underline decoration-primary/30">
              veil.app/pay/w8b4
            </p>
          </div>
        )}

        {msg.kind === 'text' && msg.from === 'bot' && (
          <p className="flex items-start gap-1.5">
            <LockKey size={13} weight="fill" className="mt-[3px] shrink-0 text-primary" />
            {msg.text}
          </p>
        )}

        {msg.kind === 'settled' && (
          <div className="min-w-[160px]">
            <p className="mb-1 flex items-center gap-1.5 font-medium">
              <CheckCircle size={14} weight="fill" className="text-accent" />
              Settled to Veil Wallet
            </p>
            <p className="font-mono text-base font-medium">18.50 USDC</p>
          </div>
        )}

        <Time t={msg.time} user={isUser} />
      </div>
    </motion.div>
  )
}

function Typing() {
  return (
    <motion.div layout {...bubbleIn} className="flex justify-start">
      <div className="flex items-center gap-1 rounded-[3px_14px_14px_14px] bg-white px-3 py-2.5 shadow-[0_1px_2px_rgba(46,0,66,0.12)]">
        {[0, 1, 2].map((d) => (
          <motion.span
            key={d}
            className="h-1.5 w-1.5 rounded-full bg-foreground/30"
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: d * 0.15 }}
          />
        ))}
      </div>
    </motion.div>
  )
}

export default function WhatsAppMockup() {
  const [count, setCount] = useState(0)

  useEffect(() => {
    let t: ReturnType<typeof setTimeout>
    const next = (n: number) => {
      if (n >= MESSAGES.length) {
        t = setTimeout(() => {
          setCount(0)
          next(0)
        }, 6000)
        return
      }
      t = setTimeout(() => {
        setCount(n + 1)
        next(n + 1)
      }, MESSAGES[n].from === 'bot' ? 1500 : 1200)
    }
    t = setTimeout(() => next(0), 1200)
    return () => clearTimeout(t)
  }, [])

  const upcoming = MESSAGES[count]
  const showTyping = count < MESSAGES.length && upcoming?.from === 'bot'

  return (
    <div className="w-[300px] shrink-0 overflow-hidden rounded-[40px] border-[7px] border-[#1a0a20] bg-[#1a0a20] shadow-[0_32px_80px_rgba(46,0,66,0.35)]">
      {/* status bar */}
      <div className="flex h-7 items-center justify-between px-5">
        <span className="text-[9px] font-medium text-white">9:41</span>
        <div className="flex items-center gap-1">
          <span className="h-1.5 w-3 rounded-sm bg-white/60" />
          <span className="h-1.5 w-1 rounded-sm bg-white/30" />
        </div>
      </div>

      {/* header */}
      <div className="flex items-center gap-3 bg-secondary px-4 py-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15">
          <Logo className="text-[9px] !text-white" />
        </span>
        <div>
          <p className="mb-[3px] text-[13px] font-semibold leading-none text-white">Veil Bot</p>
          <p className="text-[10px] text-white/60">Online</p>
        </div>
      </div>

      {/* chat */}
      <div className="flex h-[340px] flex-col justify-end gap-2 overflow-hidden bg-[#f3ecf8] p-2.5">
        <AnimatePresence initial={false}>
          {MESSAGES.slice(0, count).map((m) => (
            <Bubble key={m.id} msg={m} />
          ))}
          {showTyping && <Typing key="typing" />}
        </AnimatePresence>
      </div>

      {/* input */}
      <div className="flex items-center gap-2 bg-[#ece4f2] p-2.5">
        <div className="flex flex-1 items-center justify-between rounded-full bg-white px-3.5 py-2 text-[10.5px] text-foreground/40">
          Message
          <Microphone size={13} />
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-white">
          <PaperPlaneRight size={14} weight="fill" />
        </span>
      </div>

      {/* home indicator */}
      <div className="flex h-5 items-center justify-center">
        <span className="h-1 w-20 rounded-full bg-white/30" />
      </div>
    </div>
  )
}
