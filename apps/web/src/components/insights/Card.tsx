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
  note?: string
  badge?: string
  wide?: boolean
}

/**
 * One insight. A metric the backend cannot compute yet shows "Not tracked yet" and what it needs, never a 0
 * (the honesty rule). An estimate is labelled as one.
 */
export function InsightCard<T>({ title, metric, render, note, badge, wide = false }: CardProps<T>) {
  const { t } = useI18n()
  const notTracked = isNotTracked(metric)
  const estimate = metric.status === 'estimate'
  return (
    <article className={`card${wide ? ' card--wide' : ''}${notTracked ? ' card--not-tracked' : ''}`}>
      <header className="card__head">
        <h3 className="card__title">{title}</h3>
        {notTracked && <span className="badge badge--muted">{t('badge.notTracked')}</span>}
        {estimate && <span className="badge badge--estimate">{t('badge.estimate')}</span>}
        {!notTracked && badge && <span className="badge badge--warning">{badge}</span>}
      </header>
      {isNotTracked(metric) ? (
        <p className="card__needs">{t(`needs.${metric.needs}` as MessageKey)}</p>
      ) : (
        <>
          <div className="card__body">{render(metric as Tracked<T>)}</div>
          {(note || estimate) && <p className="card__note">{note ?? t('note.estimate')}</p>}
        </>
      )}
    </article>
  )
}

export function BigNumber({ value, caption }: { value: string; caption?: string }) {
  return (
    <p className="big-number">
      <span className="big-number__value">{value}</span>
      {caption && <span className="big-number__caption">{caption}</span>}
    </p>
  )
}
