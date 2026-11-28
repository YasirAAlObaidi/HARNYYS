import { useI18n } from '../i18n/context'
import { useTheme } from '../theme/context'
import { DeviceIcon, MoonIcon, SunIcon } from './icons'

export function LanguageToggle() {
  const { lang, setLang, t } = useI18n()
  const other = lang === 'ar' ? 'en' : 'ar'
  return (
    <button
      type="button"
      className="header-button"
      lang={other}
      aria-label={t('lang.switchLabel')}
      onClick={() => setLang(other)}
    >
      {t('lang.switch')}
    </button>
  )
}

export function ThemeToggle() {
  const { choice, cycle } = useTheme()
  const { t } = useI18n()
  const label = t(choice === 'system' ? 'theme.system' : choice === 'light' ? 'theme.light' : 'theme.dark')
  const IconFor = choice === 'system' ? DeviceIcon : choice === 'light' ? SunIcon : MoonIcon
  return (
    <button type="button" className="header-button header-button--icon" aria-label={label} title={label} onClick={cycle}>
      <IconFor />
    </button>
  )
}
