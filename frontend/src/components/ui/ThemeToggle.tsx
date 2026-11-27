import { Moon, Sun } from '@phosphor-icons/react'
import { useThemeStore } from '../../stores/themeStore'

export function ThemeToggle({ className = '' }: { className?: string }) {
  const theme = useThemeStore((state) => state.theme)
  const toggleTheme = useThemeStore((state) => state.toggleTheme)
  const isDark = theme === 'dark'
  const label = isDark ? 'Switch to light mode' : 'Switch to dark mode'

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      aria-pressed={isDark}
      title={label}
      className={`inline-flex size-8 shrink-0 items-center justify-center rounded-pill border border-primary/15 bg-surface text-foreground/75 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:size-9 ${className}`}
    >
      {isDark ? <Sun size={17} weight="bold" aria-hidden="true" /> : <Moon size={17} weight="bold" aria-hidden="true" />}
    </button>
  )
}
