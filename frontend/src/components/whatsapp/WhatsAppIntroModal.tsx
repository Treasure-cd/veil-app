import { useEffect, useRef } from 'react'
import { ArrowRight, CheckCircle, ChatCircleText, Link as LinkIcon, WhatsappLogo, X } from '@phosphor-icons/react'
import { Button } from '../ui/Button'

interface WhatsAppIntroModalProps {
  open: boolean
  onClose: () => void
  onContinue: () => void
}

const STEPS = [
  {
    icon: WhatsappLogo,
    title: 'Join the bot',
    detail: "A one-time step to open Veil's WhatsApp business chat.",
  },
  {
    icon: ChatCircleText,
    title: 'Say “hi”',
    detail: 'The bot replies with everything you can ask it to do.',
  },
  {
    icon: LinkIcon,
    title: 'Ask for a link',
    detail: 'Send “5000 jollof” or “recent” and watch the reply arrive.',
  },
]

export function WhatsAppIntroModal({ open, onClose, onContinue }: WhatsAppIntroModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="whatsapp-intro-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-panel border border-primary/10 bg-surface p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm max-sm:mb-0 max-sm:mt-auto max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-panel dark:backdrop:bg-black/65"
    >
      <div className="p-5 sm:p-7">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-card bg-[#25D366]/15 text-[#128C4A]">
              <WhatsappLogo size={22} weight="fill" aria-hidden="true" />
            </span>
            <div>
              <h2 id="whatsapp-intro-title" className="text-xl font-semibold text-primary">See Veil in action</h2>
              <p className="mt-1 text-sm text-foreground/60">Three messages. That’s the whole demo.</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex size-9 shrink-0 items-center justify-center rounded-full text-foreground/50 hover:bg-primary/5 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X size={20} />
          </button>
        </div>

        <ol className="mt-6 space-y-3">
          {STEPS.map((step, index) => {
            const Icon = step.icon
            return (
              <li key={step.title} className="flex gap-3 rounded-card border border-primary/10 bg-background/60 p-4">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Icon size={18} weight="fill" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-primary">
                    {index + 1}. {step.title}
                  </p>
                  <p className="mt-0.5 text-sm leading-relaxed text-foreground/60">{step.detail}</p>
                </div>
              </li>
            )
          })}
        </ol>

        <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-foreground/55">
          <CheckCircle size={15} className="mt-0.5 shrink-0 text-[#128C4A]" weight="fill" aria-hidden="true" />
          Next, connect the wallet that should receive demo payments, then link your number. Signing is free and moves no funds.
        </p>

        <Button className="mt-6" fullWidth size="lg" onClick={onContinue}>
          Continue to WhatsApp demo
          <ArrowRight size={18} aria-hidden="true" />
        </Button>
      </div>
    </dialog>
  )
}
