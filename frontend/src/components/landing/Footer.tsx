import { WhatsappLogo } from '@phosphor-icons/react'
import { Button } from '../ui/Button'

interface FooterProps {
  onTryWhatsApp: () => void
}

export default function Footer({ onTryWhatsApp }: FooterProps) {
  return (
    <footer className="border-t border-foreground/10 bg-surface px-6 py-8 md:px-12">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-foreground/50">© {new Date().getFullYear()} Veil</p>
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<WhatsappLogo size={17} weight="fill" />}
          onClick={onTryWhatsApp}
        >
          Try it on WhatsApp
        </Button>
      </div>
    </footer>
  )
}
