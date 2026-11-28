import { useState } from 'react'

import { useI18n } from '../../i18n/context'
import { textLang } from '../../lib/text'

export interface Part {
  label: string
  value: number
  /** A token name such as "--chart-1". */
  colour: string
}

/** One 12px bar split into parts, with each part's share labelled above it. Mirrors in Arabic. */
export function SplitBar({ parts, total: given }: { parts: Part[]; total?: number }) {
  const { fmt, t } = useI18n()
  const total = given ?? parts.reduce((sum, part) => sum + part.value, 0)
  if (total === 0) return <p className="muted">{t('stat.noData')}</p>
  return (
    <div className="split">
      <div className="split__labels">
        {parts.map((part) => (
          <span key={part.label} className="split__label">
            <span className="split__swatch" style={{ background: `var(${part.colour})` }} aria-hidden="true" />
            {part.label}
            <strong className="num">{fmt.percent(part.value / total)}</strong>
            <span className="muted num">({fmt.number(part.value)})</span>
          </span>
        ))}
      </div>
      <div className="split__bar" aria-hidden="true">
        {parts
          .filter((part) => part.value > 0)
          .map((part) => (
            <span
              key={part.label}
              className="split__part"
              style={{ inlineSize: `${(part.value / total) * 100}%`, background: `var(${part.colour})` }}
            />
          ))}
      </div>
    </div>
  )
}

export interface RankRow {
  key: string
  label: string
  value: number
  tag?: string
}

const SHOWN = 8

/**
 * A ranked list: a soft bar behind each label, as long as its count, and the count at the end. The first
 * eight show; the rest behind "Show all". Bars grow from the inline start.
 */
export function RankList({ rows, head, valueLabel }: { rows: RankRow[]; head: string; valueLabel: string }) {
  const { fmt, t } = useI18n()
  const [all, setAll] = useState(false)
  if (rows.length === 0) return <p className="muted">{t('stat.noData')}</p>
  const top = Math.max(...rows.map((row) => row.value), 1)
  const shown = all ? rows : rows.slice(0, SHOWN)
  return (
    <div className="rank">
      <p className="rank__head" aria-hidden="true">
        <span>{head}</span>
        <span>{valueLabel}</span>
      </p>
      <ol className="rank__rows">
        {shown.map((row) => (
          <li key={row.key} className="rank__row">
            <span className="rank__fill" style={{ inlineSize: `${(row.value / top) * 100}%` }} aria-hidden="true" />
            <span className="rank__label" dir="auto" lang={textLang(row.label)}>
              {row.label}
            </span>
            {row.tag && <span className="chip rank__tag">{row.tag}</span>}
            <span className="rank__value num" aria-label={`${valueLabel}: ${fmt.number(row.value)}`}>
              {fmt.number(row.value)}
            </span>
          </li>
        ))}
      </ol>
      {rows.length > SHOWN && (
        <button type="button" className="btn btn--ghost rank__more" onClick={() => setAll((value) => !value)}>
          {all ? t('list.showLess') : t('list.showAll', { n: fmt.number(rows.length) })}
        </button>
      )}
    </div>
  )
}
