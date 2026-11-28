import type { CSSProperties } from 'react'

import type { Heatmap as HeatmapData } from '../../api/types'
import { useI18n } from '../../i18n/context'

const HOURS = Array.from({ length: 24 }, (_, hour) => hour)

/**
 * Messages by weekday (Monday first) and hour, in the client's timezone. A real table, so screen readers can
 * read it and it mirrors by itself in Arabic: hours then run from right to left.
 */
export function Heatmap({ data, caption }: { data: HeatmapData; caption: string }) {
  const { t, fmt } = useI18n()
  const hour = (h: number) => `${String(h).padStart(2, '0')}:00`
  return (
    <div className="heatmap">
      <div className="heatmap__scroll">
        <table className="heatmap__table">
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">
                <span className="visually-hidden">{t('label.day')}</span>
              </th>
              {HOURS.map((h) => (
                <th key={h} scope="col" className="heatmap__hour">
                  {h % 3 === 0 ? String(h).padStart(2, '0') : <span className="visually-hidden">{hour(h)}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.cells.map((row, day) => (
              <tr key={day}>
                <th scope="row" className="heatmap__day">
                  {fmt.weekday(day)}
                </th>
                {row.map((count, h) => {
                  const label = t('heatmap.cell', { day: fmt.weekday(day), hour: hour(h), n: fmt.number(count) })
                  return (
                    <td
                      key={h}
                      className="heatmap__cell"
                      title={label}
                      style={{ '--level': data.max > 0 ? count / data.max : 0 } as CSSProperties}
                    >
                      <span className="visually-hidden">{label}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="heatmap__legend" aria-hidden="true">
        <span>{t('heatmap.fewer')}</span>
        <span className="heatmap__ramp" />
        <span>{t('heatmap.more')}</span>
      </p>
    </div>
  )
}
