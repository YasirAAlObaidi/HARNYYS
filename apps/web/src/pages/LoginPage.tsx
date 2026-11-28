import { Eye, EyeOff, CircleAlert, Clock } from 'lucide-react'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import { useLogin } from '../api/queries'
import { LanguageToggle } from '../components/HeaderControls'
import { Logo } from '../components/Logo'
import { OtpField } from '../components/OtpField'
import { useI18n } from '../i18n/context'
import { normaliseCode } from '../lib/digits'

/**
 * Sign in, in two steps in one card (docs/decisions/0014): username and password, then the 6-digit code
 * from an authenticator app. Nothing is sent until the code is in; then all three go in one request, and a
 * failure never says which part was wrong.
 */
export function LoginPage() {
  const { t } = useI18n()
  const login = useLogin()
  const [step, setStep] = useState<'credentials' | 'code'>('credentials')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [code, setCode] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0) // re-mounts the code cells, which replays the shake
  const [lockedUntil, setLockedUntil] = useState<number | null>(null)
  const [now, setNow] = useState(0)
  const codeBox = useRef<HTMLDivElement | null>(null)

  // A live countdown while logins are locked.
  useEffect(() => {
    if (lockedUntil === null) return
    const timer = window.setInterval(() => {
      const current = Date.now()
      setNow(current)
      if (current >= lockedUntil) setLockedUntil(null)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [lockedUntil])

  useEffect(() => {
    if (step === 'code') codeBox.current?.querySelector('input')?.focus()
  }, [step, attempt])

  function toCode(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setProblem(t('login.needBoth'))
      return
    }
    setProblem(null)
    setStep('code')
  }

  async function signIn(value: string) {
    const digits = normaliseCode(value)
    if (!digits) {
      setProblem(t('login.codeInvalid'))
      return
    }
    setProblem(null)
    try {
      await login.mutateAsync({ username: username.trim(), password, code: digits })
    } catch (error) {
      setCode('')
      setAttempt((n) => n + 1)
      if (error instanceof ApiError && error.status === 429) {
        const current = Date.now()
        setNow(current)
        setLockedUntil(current + (error.retryAfterS ?? 60) * 1000)
        setProblem(null)
      } else if (error instanceof ApiError && error.status === 401) {
        setProblem(t('login.failed'))
      } else if (error instanceof ApiError && error.status === 0) {
        setProblem(t('error.network'))
      } else {
        setProblem(t('error.generic'))
      }
    }
  }

  const left = lockedUntil === null ? 0 : Math.max(0, Math.ceil((lockedUntil - now) / 1000))
  const wait = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`

  return (
    <div className="login">
      <Lattice />
      <div className="login__top">
        <LanguageToggle className="btn btn--ghost" />
      </div>
      <main className="login__main">
        <div className="login__card">
          <Logo label={t('app.name')} className="login__logo" />
          <h1 className="login__title display">{t('login.title')}</h1>
          <p className="login__intro">{t('login.intro')}</p>

          {lockedUntil !== null && (
            <p className="banner banner--warning" role="status">
              <Clock size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>{t('login.throttled', { time: wait })}</span>
            </p>
          )}

          {step === 'credentials' ? (
            <form className="login__form" onSubmit={toCode} noValidate>
              <label className="field">
                <span className="field__label">{t('login.username')}</span>
                <input
                  className="input input--lg"
                  name="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  dir="ltr"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </label>
              <div className="field">
                <label className="field__label" htmlFor="login-password">
                  {t('login.password')}
                </label>
                <div className="password">
                  <input
                    id="login-password"
                    className="input input--lg"
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    autoComplete="current-password"
                    dir="ltr"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <button
                    type="button"
                    className="password__toggle"
                    aria-label={showPassword ? t('login.hidePassword') : t('login.showPassword')}
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((value) => !value)}
                  >
                    {showPassword ? <EyeOff size={18} strokeWidth={1.5} /> : <Eye size={18} strokeWidth={1.5} />}
                  </button>
                </div>
              </div>
              {problem && <Problem text={problem} />}
              <button type="submit" className="btn btn--primary btn--lg btn--wide">
                {t('login.continue')}
              </button>
            </form>
          ) : (
            <form
              className="login__form"
              onSubmit={(event) => {
                event.preventDefault()
                void signIn(code)
              }}
              noValidate
            >
              <div className="login__summary">
                <span dir="ltr">{username.trim()}</span>
                <button
                  type="button"
                  className="login__change"
                  onClick={() => {
                    setStep('credentials')
                    setCode('')
                    setProblem(null)
                  }}
                >
                  {t('login.change')}
                </button>
              </div>
              <p className="login__code-title">{t('login.codeTitle')}</p>
              <div ref={codeBox} key={attempt} className={attempt > 0 && problem ? 'shake' : undefined}>
                <OtpField
                  value={code}
                  onChange={setCode}
                  onComplete={(value) => void signIn(value)}
                  label={t('login.code')}
                  describedBy="login-code-hint"
                  invalid={Boolean(problem)}
                  disabled={login.isPending || lockedUntil !== null}
                />
              </div>
              <p className="login__hint" id="login-code-hint">
                {t('login.codeHint')}
              </p>
              {problem && <Problem text={problem} />}
              <button
                type="submit"
                className="btn btn--primary btn--lg btn--wide"
                disabled={login.isPending || lockedUntil !== null}
              >
                {login.isPending && <span className="spinner" aria-hidden="true" />}
                {login.isPending ? t('login.submitting') : t('login.submit')}
              </button>
            </form>
          )}
          <p className="login__help">{t('login.help')}</p>
        </div>
      </main>
    </div>
  )
}

function Problem({ text }: { text: string }) {
  return (
    <p className="banner banner--danger" role="alert">
      <CircleAlert size={16} strokeWidth={1.5} aria-hidden="true" />
      <span>{text}</span>
    </p>
  )
}

/** The one ornament: a faint 8-point Gulf lattice in gold, fading out from the top. Inline SVG, no image file. */
function Lattice() {
  return (
    <svg className="login__lattice" aria-hidden="true" focusable="false">
      <defs>
        <pattern id="kh-lattice" width="56" height="56" patternUnits="userSpaceOnUse">
          <g fill="none" stroke="currentColor" strokeWidth="0.75">
            <rect x="16" y="16" width="24" height="24" />
            <rect x="16" y="16" width="24" height="24" transform="rotate(45 28 28)" />
            <path d="M0 28h11M45 28h11M28 0v11M28 45v11" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#kh-lattice)" />
    </svg>
  )
}
