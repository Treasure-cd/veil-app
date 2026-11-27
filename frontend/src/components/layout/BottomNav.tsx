import { NavLink } from 'react-router'
import { getVisibleNavItems } from './nav'
import { motion } from 'framer-motion'
import { useAuth } from '../../auth/useAuth'

export function BottomNav() {
  const { user } = useAuth()
  const items = getVisibleNavItems(user?.isAdmin)

  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-primary/10 bg-surface/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="grid grid-flow-col auto-cols-fr">
        {items.map(({ to, label, icon: Icon }) => (
          <li key={to} className="min-w-0">
            <NavLink
              to={to}
              end={to === '/app'}
              className={({ isActive }) =>
                [
                  'relative flex flex-col items-center justify-center gap-1 px-1 py-2.5 text-[11px] font-medium transition-colors sm:text-xs',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent',
                  isActive ? 'text-primary' : 'text-foreground/60',
                ].join(' ')
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="bottom-nav-indicator"
                      className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-primary sm:inset-x-5"
                      transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                    />
                  )}
                  <Icon size={21} weight={isActive ? 'fill' : 'regular'} />
                  <span className="max-w-full truncate">{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
