import { BarChart3, LogOut, MessagesSquare, Sparkles, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router'

import { useLogout } from '../api/queries'
import type { StaffUser } from '../api/types'
import logo from '../assets/kahraman-logo-white.svg'
import mark from '../assets/kahraman-mark.svg'
import { useI18n } from '../i18n/context'
import { can } from '../lib/permissions'
import { initial } from '../lib/people'
import { LanguageToggle, ThemeSwitch } from './HeaderControls'

const ICON = { size: 18, strokeWidth: 1.5, 'aria-hidden': true } as const

/**
 * The app shell: the green navigation rail at the inline start (a sidebar, then an icon rail on smaller
 * screens) and, on a phone, a bottom tab bar. There is no top bar: each page has its own header.
 */
export function Layout({ user }: { user: StaffUser }) {
  const { t } = useI18n()
  const drill = useMatch('/chats/:id') !== null // an open chat on a phone hides the tab bar
  const pages = [
    { to: '/chats', label: t('nav.chats'), Icon: MessagesSquare, show: can(user, 'chats') },
    { to: '/assistant', label: t('nav.assistant'), Icon: Sparkles, show: can(user, 'assistant') },
    { to: '/insights', label: t('nav.insights'), Icon: BarChart3, show: can(user, 'insights') },
  ].filter((page) => page.show)

  return (
    <div className={`shell${drill ? ' shell--drill' : ''}`}>
      <nav className="sidebar" aria-label={t('nav.main')}>
        <div className="sidebar__brand">
          <img src={logo} alt={t('app.name')} className="sidebar__logo" width="95" height="30" />
          <img src={mark} alt={t('app.name')} className="sidebar__mark" width="28" height="28" />
        </div>
        {pages.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className="nav-item" title={label}>
            <Icon {...ICON} />
            <span className="nav-item__label">{label}</span>
          </NavLink>
        ))}
        <div className="sidebar__foot">
          <LanguageToggle className="nav-item" />
          <ThemeSwitch />
          <UserChip user={user} />
        </div>
      </nav>

      <main className="shell__main" id="main">
        <Outlet />
      </main>

      <TabBar pages={pages} user={user} />
    </div>
  )
}

function UserChip({ user }: { user: StaffUser }) {
  const { t } = useI18n()
  const logout = useLogout()
  const name = user.display_name ?? user.username
  return (
    <div className="user-chip">
      <span className="avatar" aria-hidden="true">
        {initial(name)}
      </span>
      <span className="user-chip__text">
        <span className="user-chip__name" title={user.username}>
          {name}
        </span>
        <span className="user-chip__role">{t(`role.${user.role}`)}</span>
      </span>
      <button
        type="button"
        className="nav-icon-button"
        aria-label={t('user.logout')}
        title={t('user.logout')}
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
      >
        <LogOut {...ICON} className="icon-directional" />
      </button>
    </div>
  )
}

interface Page {
  to: string
  label: string
  Icon: typeof MessagesSquare
}

/** Phone navigation: the pages, then Account (language, theme, sign out) in a small sheet. */
function TabBar({ pages, user }: { pages: Page[]; user: StaffUser }) {
  const { t } = useI18n()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const sheet = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !sheet.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', close)
    return () => {
      document.removeEventListener('keydown', close)
      document.removeEventListener('pointerdown', close)
    }
  }, [open])

  return (
    <>
      <nav className="tabbar" aria-label={t('nav.main')}>
        {pages.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className="tab">
            <Icon size={20} strokeWidth={1.5} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          className="tab"
          aria-expanded={open}
          aria-haspopup="dialog"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => setOpen((value) => !value)}
        >
          <UserRound size={20} strokeWidth={1.5} aria-hidden="true" />
          <span>{t('nav.account')}</span>
        </button>
      </nav>
      {open && (
        <div className="sheet" role="dialog" aria-label={t('nav.account')} ref={sheet}>
          <div className="sheet__row">
            <span className="user-chip__text">
              <span className="user-chip__name">{user.display_name ?? user.username}</span>
              <span className="muted">{t(`role.${user.role}`)}</span>
            </span>
            <button type="button" className="btn" onClick={() => logout.mutate()} disabled={logout.isPending}>
              <LogOut {...ICON} className="icon-directional" />
              {t('user.logout')}
            </button>
          </div>
          <div className="sheet__row">
            <span>{t('lang.label')}</span>
            <LanguageToggle className="btn" />
          </div>
          <div className="sheet__row">
            <span>{t('theme.label')}</span>
            <ThemeSwitch />
          </div>
        </div>
      )}
    </>
  )
}
