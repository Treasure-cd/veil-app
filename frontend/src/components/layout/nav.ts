import { ArrowsLeftRight, GearSix, SquaresFour, UsersThree, type Icon } from '@phosphor-icons/react'

export interface NavItem {
  to: string
  label: string
  icon: Icon
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: SquaresFour },
  { to: '/payments', label: 'Payments', icon: ArrowsLeftRight },
  { to: '/payroll', label: 'Payroll', icon: UsersThree },
  { to: '/settings', label: 'Settings', icon: GearSix },
]
