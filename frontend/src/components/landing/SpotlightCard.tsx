import { motion, useMotionTemplate, useMotionValue } from 'framer-motion'
import type { ReactNode } from 'react'

export default function SpotlightCard({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  const x = useMotionValue(-400)
  const y = useMotionValue(-400)
  const glow = useMotionTemplate`radial-gradient(320px circle at ${x}px ${y}px, rgba(92,4,159,0.10), transparent 70%)`

  return (
    <motion.div
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        x.set(e.clientX - r.left)
        y.set(e.clientY - r.top)
      }}
      initial={{ opacity: 0, y: 32 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -4 }}
      className={`group relative overflow-hidden rounded-3xl border border-foreground/10 bg-white p-8 shadow-[0_2px_24px_rgba(46,0,66,0.05)] ${className}`}
    >
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: glow }}
      />
      <div className="relative">{children}</div>
    </motion.div>
  )
}
