import { NavLink, Outlet } from 'react-router'

import { useLogout } from '../api/queries'
import type { StaffUser } from '../api/types'
import logo from '../assets/kahraman-logo-white.svg'
import { useI18n } from '../i18n/context'
import { can } from '../lib/permissions'
import { LanguageToggle, ThemeToggle } from './HeaderControls'
import { LogoutIcon } from './icons'

/** The header (logo, pages, language, theme, user) and the page below it. */
export function Layout({ user }: { user: StaffUser }) {
  const { t } = useI18n()
  const logout = useLogout()
  const pages = [
    { to: '/chats', label: t('nav.chats'), show: can(user, 'chats') },
    { to: '/assistant', label: t('nav.assistant'), show: can(user, 'assistant') },
    { to: '/insights', label: t('nav.insights'), show: can(user, 'insights') },
  ].filter((page) => page.show)

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__brand">
          <img src={logo} alt={t('app.name')} className="app-header__logo" width="101" height="32" />
          <span className="app-header__staff">{t('app.staff')}</span>
        </div>
        <nav className="app-nav" aria-label={t('nav.main')}>
          {pages.map((page) => (
            <NavLink key={page.to} to={page.to} className="app-nav__link">
              {page.label}
            </NavLink>
          ))}
        </nav>
        <div className="app-header__tools">
          <LanguageToggle />
          <ThemeToggle />
          <span className="app-header__user" title={user.username}>
            <span className="app-header__user-name">{user.display_name ?? user.username}</span>
            <span className="app-header__role">{t(`role.${user.role}`)}</span>
          </span>
          <button
            type="button"
            className="header-button header-button--icon"
            aria-label={t('user.logout')}
            title={t('user.logout')}
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            <LogoutIcon />
          </button>
        </div>
      </header>
      <main className="app-main" id="main">
        <Outlet />
      </main>
    </div>
  )
}
