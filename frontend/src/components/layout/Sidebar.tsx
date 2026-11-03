import { NavLink } from 'react-router'
import { NAV_ITEMS } from './nav'
import { motion } from 'framer-motion'

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-primary/10 bg-white md:flex">
      <div className="flex h-16 items-center px-6">
        <span className="text-xl font-semibold tracking-tight text-primary">Veil</span>
      </div>

      <nav aria-label="Main" className="flex flex-col gap-1 px-3 py-4">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'relative flex h-10 items-center gap-3 rounded-card px-3 text-sm font-semibold transition-colors',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                isActive
                  ? 'text-primary'
                  : 'text-foreground/70 hover:bg-primary/5 hover:text-foreground',
              ].join(' ')
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="sidebar-indicator"
                    className="absolute inset-0 rounded-card bg-primary/10"
                    transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                  />
                )}
                <Icon size={20} weight={isActive ? 'fill' : 'regular'} className="relative" />
                <span className="relative">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
