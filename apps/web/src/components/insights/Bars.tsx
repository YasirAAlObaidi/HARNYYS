import type { CSSProperties } from 'react'

import { useI18n } from '../../i18n/context'

export interface Part {
  label: string
  value: number
  /** A token name such as "--chart-1". */
  colour: string
}

/** One bar split into parts (new vs returning, Arabic vs English), with a legend. Mirrors in Arabic. */
export function SplitBar({ parts }: { parts: Part[] }) {
  const { fmt, t } = useI18n()
  const total = parts.reduce((sum, part) => sum + part.value, 0)
  if (total === 0) return <p className="muted">{t('stat.noData')}</p>
  return (
    <div className="split">
      <div className="split__bar" role="img" aria-label={parts.map((p) => `${p.label} ${fmt.number(p.value)}`).join(', ')}>
        {parts
          .filter((part) => part.value > 0)
          .map((part) => (
            <span
              key={part.label}
              className="split__part"
              style={{ inlineSize: `${(part.value / total) * 100}%`, background: `var(${part.colour})` } as CSSProperties}
            />
          ))}
      </div>
      <ul className="legend">
        {parts.map((part) => (
          <li key={part.label} className="legend__item">
            <span className="legend__swatch" style={{ background: `var(${part.colour})` }} aria-hidden="true" />
            <span className="legend__label">{part.label}</span>
            <span className="legend__value">
              {fmt.number(part.value)} <span className="muted">({fmt.percent(part.value / total)})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export interface RankRow {
  key: string
  label: string
  value: number
  detail?: string
  tag?: string
}

/** A short ranked list with a bar per row, longest first. Bars grow from the inline start. */
export function RankList({ rows, valueLabel }: { rows: RankRow[]; valueLabel: string }) {
  const { fmt, t } = useI18n()
  if (rows.length === 0) return <p className="muted">{t('stat.noData')}</p>
  const top = Math.max(...rows.map((row) => row.value), 1)
  return (
    <ol className="rank">
      {rows.map((row) => (
        <li key={row.key} className="rank__row">
          <span className="rank__label">
            <bdi>{row.label}</bdi>
            {row.tag && <span className="chip chip--small">{row.tag}</span>}
          </span>
          <span className="rank__value" aria-label={`${valueLabel}: ${fmt.number(row.value)}`}>
            {fmt.number(row.value)}
            {row.detail && <span className="muted"> · {row.detail}</span>}
          </span>
          <span className="rank__track" aria-hidden="true">
            <span className="rank__fill" style={{ inlineSize: `${(row.value / top) * 100}%` }} />
          </span>
        </li>
      ))}
    </ol>
  )
}
