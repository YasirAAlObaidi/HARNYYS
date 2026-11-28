import { ArrowDownRight, ArrowUpRight, CircleDashed, Info, Minus } from 'lucide-react'
import type { ReactNode } from 'react'

import type { Metric } from '../../api/types'
import { useI18n } from '../../i18n/context'
import type { MessageKey } from '../../i18n/messages'
import { isNotTracked, type Tracked } from '../../lib/metrics'

interface CardProps<T> {
  title: string
  metric: Metric<T>
  /** Shown only when the metric has data. */
  render: (metric: Tracked<T>) => ReactNode
  /** Grid span out of 12 on wide screens. */
  span?: 3 | 4 | 6 | 8 | 12
  /** The definition, shown behind an info icon. */
  definition?: string
  note?: string
  /** An extra chip, e.g. "Working hours not confirmed". */
  chip?: string
  /** A KPI card with no data source shows a dash in the value's place. */
  kpi?: boolean
}

/**
 * One insight. A metric the backend cannot compute yet keeps the card's size and place, shows a dash and
 * "Not tracked yet" with what it needs, and never a 0 (the honesty rule). An estimate is labelled as one.
 */
export function InsightCard<T>({ title, metric, render, span = 4, definition, note, chip, kpi }: CardProps<T>) {
  const { t } = useI18n()
  const estimate = metric.status === 'estimate'
  return (
    <article className={`card card--span-${span}${isNotTracked(metric) ? ' card--not-tracked' : ''}`}>
      <header className="card__head">
        <span className="card__title-row">
          <h3 className="card__title">{title}</h3>
          {definition && (
            <span className="card__info" title={definition} aria-label={definition} role="img">
              <Info size={14} strokeWidth={1.5} aria-hidden="true" />
            </span>
          )}
        </span>
        {estimate && <span className="chip chip--gold">{t('badge.estimate')}</span>}
        {!isNotTracked(metric) && chip && <span className="chip chip--warning">{chip}</span>}
      </header>
      {isNotTracked(metric) ? (
        <>
          {kpi && (
            <p className="kpi__value kpi__value--none" aria-hidden="true">
              —
            </p>
          )}
          <span className="chip chip--dashed card__not-tracked">
            <CircleDashed size={12} strokeWidth={1.5} aria-hidden="true" />
            {t('badge.notTracked')}
          </span>
          <p className="card__needs">{t(`needs.${metric.needs}` as MessageKey)}</p>
        </>
      ) : (
        <>
          <div className="card__body">{render(metric as Tracked<T>)}</div>
          {(note || estimate) && <p className="card__note">{note ?? t('note.estimate')}</p>}
        </>
      )}
    </article>
  )
}

/** A big number in the display face, with an optional unit after it. */
export function KpiValue({ value, unit }: { value: string; unit?: string }) {
  return (
    <p className="kpi__value">
      {value}
      {unit && <span className="kpi__unit">{unit}</span>}
    </p>
  )
}

/**
 * The change against the previous period: an arrow, a sign and a percentage, so colour is never the only
 * cue. `good` says which way is good ("up" for leads); "neutral" keeps it grey. Within ±2% counts as flat.
 */
export function Delta({
  now,
  before,
  versus,
  good = 'up',
}: {
  now: number
  before: number | null | undefined
  versus: string
  good?: 'up' | 'down' | 'neutral'
}) {
  const { t, fmt } = useI18n()
  if (before === null || before === undefined) return <p className="delta delta--none">{t('delta.none')}</p>
  if (before === 0) {
    if (now === 0) return <p className="delta delta--flat">{t('delta.same')} · {versus}</p>
    return (
      <p className={`delta ${good === 'neutral' ? 'delta--flat' : good === 'up' ? 'delta--good' : 'delta--bad'}`}>
        <ArrowUpRight size={14} strokeWidth={2} aria-hidden="true" />
        {t('delta.fromZero')} · {versus}
      </p>
    )
  }
  const change = (now - before) / before
  const flat = Math.abs(change) < 0.02
  const tone = flat || good === 'neutral' ? 'flat' : (change > 0) === (good === 'up') ? 'good' : 'bad'
  const Icon = flat ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <p className={`delta delta--${tone}`}>
      <Icon size={14} strokeWidth={2} aria-hidden="true" />
      <span className="num">
        {change > 0 ? '+' : flat ? '' : '−'}
        {fmt.percent(Math.abs(change))}
      </span>
      <span className="delta__versus">{versus}</span>
    </p>
  )
}
