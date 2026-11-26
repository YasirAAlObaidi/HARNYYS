import { type FormEvent, useState } from 'react'

import { ApiError } from '../api/client'
import { useLogin } from '../api/queries'
import logo from '../assets/kahraman-logo-white.svg'
import { LanguageToggle, ThemeToggle } from '../components/HeaderControls'
import { useI18n } from '../i18n/context'
import { normaliseCode } from '../lib/digits'

/** Username, password and the 6-digit code from an authenticator app (docs/decisions/0014). */
export function LoginPage() {
  const { t } = useI18n()
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const digits = normaliseCode(code)
    if (!digits) {
      setProblem(t('login.codeInvalid'))
      return
    }
    setProblem(null)
    try {
      await login.mutateAsync({ username: username.trim(), password, code: digits })
    } catch (error) {
      setCode('')
      if (error instanceof ApiError && error.status === 429) {
        setProblem(t('login.throttled', { minutes: Math.max(1, Math.ceil((error.retryAfterS ?? 60) / 60)) }))
      } else if (error instanceof ApiError && error.status === 401) {
        setProblem(t('login.failed'))
      } else if (error instanceof ApiError && error.status === 0) {
        setProblem(t('error.network'))
      } else {
        setProblem(t('error.generic'))
      }
    }
  }

  return (
    <div className="login">
      <header className="login__header">
        <img src={logo} alt={t('app.name')} className="login__logo" width="152" height="48" />
        <div className="login__tools">
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </header>
      <main className="login__main">
        <form className="login__card" onSubmit={submit} noValidate>
          <h1 className="login__title">{t('login.title')}</h1>
          <p className="login__intro">{t('login.intro')}</p>

          <label className="field">
            <span className="field__label">{t('login.username')}</span>
            <input
              className="field__input"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              dir="ltr"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>

          <label className="field">
            <span className="field__label">{t('login.password')}</span>
            <input
              className="field__input"
              type="password"
              name="password"
              autoComplete="current-password"
              dir="ltr"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <div className="field">
            <label className="field__label" htmlFor="login-code">
              {t('login.code')}
            </label>
            <input
              id="login-code"
              className="field__input field__input--code"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              dir="ltr"
              maxLength={12}
              required
              value={code}
              onChange={(event) => setCode(event.target.value)}
              aria-describedby="login-code-hint"
            />
            <span className="field__hint" id="login-code-hint">
              {t('login.codeHint')}
            </span>
          </div>

          {problem && (
            <p className="form-error" role="alert">
              {problem}
            </p>
          )}

          <button type="submit" className="button button--primary button--wide" disabled={login.isPending}>
            {login.isPending ? t('login.submitting') : t('login.submit')}
          </button>
          <p className="login__help">{t('login.help')}</p>
        </form>
      </main>
    </div>
  )
}
