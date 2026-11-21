import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type MoneyDisplayMode = 'ngn' | 'token'

interface DisplayState {
  moneyDisplayMode: MoneyDisplayMode
  setMoneyDisplayMode: (mode: MoneyDisplayMode) => void
}

export const useDisplayStore = create<DisplayState>()(
  persist(
    (set) => ({
      moneyDisplayMode: 'ngn',
      setMoneyDisplayMode: (moneyDisplayMode) => set({ moneyDisplayMode }),
    }),
    {
      name: 'veil-display-preferences',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ moneyDisplayMode: state.moneyDisplayMode }),
    },
  ),
)
