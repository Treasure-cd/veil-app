import { useState } from 'react'
import { Link } from 'react-router'
import { motion, useScroll, useMotionValueEvent } from 'framer-motion'
import Logo from '../Logo'
import { OpenAppButton } from './OpenAppButton'

const LINKS = [
  { label: 'How it works', href: '#how' },
  { label: 'Payroll', href: '#payroll' },
  { label: 'Pricing', href: '#pricing' },
]

export default function Navbar() {
  const { scrollY } = useScroll()
  const [scrolled, setScrolled] = useState(false)
  const [hovered, setHovered] = useState<string | null>(null)

  useMotionValueEvent(scrollY, 'change', (v) => setScrolled(v > 24))

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center px-8">
      <motion.nav
        initial={{ y: -80, opacity: 0 }}
        animate={{ y: 0, opacity: 1, maxWidth: scrolled ? 620 : 880 }}
        transition={{ type: 'spring', stiffness: 120, damping: 18 }}
        className="pointer-events-auto flex w-full items-center justify-between rounded-full border border-foreground/10 bg-white/70 py-2 pl-6 pr-6 shadow-[0_8px_32px_rgba(46,0,66,0.08)] backdrop-blur-xl"
      >
        <Link to="/" className="text-lg">
          <Logo className="h-5" />
        </Link>

        <ul className="hidden items-center gap-1 md:flex" onMouseLeave={() => setHovered(null)}>
          {LINKS.map((l) => (
            <li key={l.label} className="relative">
              <a
                href={l.href}
                onMouseEnter={() => setHovered(l.label)}
                className="relative z-10 block px-4 py-2 text-sm text-foreground/70 transition-colors hover:text-foreground"
              >
                {l.label}
              </a>
              {hovered === l.label && (
                <motion.span
                  layoutId="nav-hover"
                  className="absolute inset-0 rounded-full bg-primary/10"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
            </li>
          ))}
        </ul>

        <OpenAppButton className="inline-flex h-10 items-center rounded-lg bg-primary px-5 text-sm font-medium text-white shadow-veil-md transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" />
      </motion.nav>
    </div>
  )
}
