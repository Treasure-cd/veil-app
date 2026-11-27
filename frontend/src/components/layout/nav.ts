import { ArrowsLeftRight, GearSix, ShieldCheck, SquaresFour, UsersThree, type Icon } from '@phosphor-icons/react'

export interface NavItem {
  to: string
  label: string
  icon: Icon
  adminOnly?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/app', label: 'Dashboard', icon: SquaresFour },
  { to: '/payments', label: 'Payments', icon: ArrowsLeftRight },
  { to: '/payroll', label: 'Payroll', icon: UsersThree },
  { to: '/admin', label: 'Admin', icon: ShieldCheck, adminOnly: true },
  { to: '/settings', label: 'Settings', icon: GearSix },
]

export function getVisibleNavItems(isAdmin?: boolean): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.adminOnly || Boolean(isAdmin))
}
