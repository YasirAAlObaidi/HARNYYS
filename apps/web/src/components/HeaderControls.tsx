import { Languages, Monitor, Moon, Sun } from 'lucide-react'

import { useI18n } from '../i18n/context'
import { type ThemeChoice, useTheme } from '../theme/context'

/** Switches English and Arabic. `compact` shows only "ع" / "EN" (the icon rail). */
export function LanguageToggle({ className = 'btn btn--ghost', compact = false }: { className?: string; compact?: boolean }) {
  const { lang, setLang, t } = useI18n()
  const other = lang === 'ar' ? 'en' : 'ar'
  return (
    <button
      type="button"
      className={className}
      lang={other}
      aria-label={t('lang.switchLabel')}
      title={t('lang.switchLabel')}
      onClick={() => setLang(other)}
    >
      <Languages size={18} strokeWidth={1.5} aria-hidden="true" />
      <span className="nav-item__label">{compact ? t('lang.short') : t('lang.switch')}</span>
    </button>
  )
}

const OPTIONS: { choice: ThemeChoice; Icon: typeof Sun; key: 'theme.system' | 'theme.light' | 'theme.dark' }[] = [
  { choice: 'system', Icon: Monitor, key: 'theme.system' },
  { choice: 'light', Icon: Sun, key: 'theme.light' },
  { choice: 'dark', Icon: Moon, key: 'theme.dark' },
]

/** System / Light / Dark. "System" follows the device; the choice is remembered in this browser. */
export function ThemeSwitch() {
  const { choice, setChoice } = useTheme()
  const { t } = useI18n()
  return (
    <div className="theme-switch" role="group" aria-label={t('theme.label')}>
      {OPTIONS.map(({ choice: option, Icon, key }) => (
        <button
          key={option}
          type="button"
          className="theme-switch__option"
          aria-pressed={choice === option}
          aria-label={t(key)}
          title={t(key)}
          onClick={() => setChoice(option)}
        >
          <Icon size={16} strokeWidth={1.5} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
