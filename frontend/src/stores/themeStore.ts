import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'veil-theme'

function readStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

function getSystemTheme(): Theme {
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

export function applyThemeToDocument(theme: Theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const initialTheme: Theme = typeof window === 'undefined' ? 'light' : (readStoredTheme() ?? getSystemTheme())
applyThemeToDocument(initialTheme)

if (typeof window !== 'undefined' && window.matchMedia) {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener('change', (event) => {
    if (readStoredTheme() === null) {
      const next: Theme = event.matches ? 'dark' : 'light'
      applyThemeToDocument(next)
      useThemeStore.setState({ theme: next })
    }
  })
}

export const useThemeStore = create<ThemeState>()((set, get) => ({
  theme: initialTheme,
  setTheme: (theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Storage may be unavailable; keep the live DOM class updated.
    }
    applyThemeToDocument(theme)
    set({ theme })
  },
  toggleTheme: () => {
    const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
    get().setTheme(next)
  },
}))
