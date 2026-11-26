import type { ReactNode } from 'react'
import { Link, Navigate } from 'react-router'

import { useMe } from '../api/queries'
import type { Permission } from '../api/types'
import { useI18n } from '../i18n/context'
import { can } from '../lib/permissions'
import { LoginPage } from '../pages/LoginPage'
import { Layout } from './Layout'

/** Shows the login page until there is a session, then the app. */
export function Gate() {
  const me = useMe()
  const { t } = useI18n()
  if (me.isPending) return <p className="splash">{t('loading')}</p>
  if (me.isError) {
    return (
      <div className="splash">
        <p className="form-error" role="alert">
          {t('error.network')}
        </p>
        <button type="button" className="button" onClick={() => me.refetch()}>
          {t('retry')}
        </button>
      </div>
    )
  }
  if (!me.data) return <LoginPage />
  return <Layout user={me.data} />
}

/** A page the user's role may not open sends them back to Chats. The API refuses it anyway. */
export function Allowed({ permission, children }: { permission: Permission; children: ReactNode }) {
  const me = useMe()
  if (!me.data || !can(me.data, permission)) return <Navigate to="/chats" replace />
  return children
}

export function NotFound() {
  const { t } = useI18n()
  return (
    <div className="pad">
      <h1 className="page-title">{t('notFound.title')}</h1>
      <Link to="/chats">{t('notFound.back')}</Link>
    </div>
  )
}
