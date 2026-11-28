import type { CSSProperties } from 'react'

import type { Heatmap as HeatmapData, InsightSnapshot } from '../../api/types'
import { useI18n } from '../../i18n/context'

const HOURS = Array.from({ length: 24 }, (_, hour) => hour)
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const STEPS = 7

/** 0 for no messages (an untinted cell), else 1-7 on the amber scale. */
function level(count: number, max: number): number {
  return count <= 0 || max <= 0 ? 0 : Math.max(1, Math.ceil((count / max) * STEPS))
}

/** "09:00-18:00" -> [9, 18): the hour columns inside working hours. */
function hoursOf(value: unknown): [number, number] | null {
  const match = typeof value === 'string' ? /^(\d\d):(\d\d)-(\d\d):(\d\d)$/.exec(value) : null
  if (!match) return null
  const end = Number(match[3]) + (Number(match[4]) > 0 ? 1 : 0)
  return [Number(match[1]), Math.min(24, end)]
}

/**
 * Messages by weekday (Monday first) and hour, in Dubai time. Seven rows by 24 hours on a wide screen, and
 * turned to 24 rows by seven days on a phone so nothing scrolls sideways (CSS places each cell from its
 * --d and --h). Working hours get a dashed outline. Screen readers get the same numbers as a table.
 */
export function Heatmap({
  data,
  caption,
  workingHours,
}: {
  data: HeatmapData
  caption: string
  workingHours?: InsightSnapshot['working_hours']
}) {
  const { t, fmt } = useI18n()
  const hour = (h: number) => `${String(h).padStart(2, '0')}:00`
  const cellLabel = (day: number, h: number, n: number) =>
    t('heatmap.cell', { day: fmt.weekday(day), hour: `${hour(h)}–${hour((h + 1) % 24)}`, n: fmt.number(n) })

  return (
    <div className="heatmap">
      <div className="heatmap__grid" aria-hidden="true">
        {HOURS.filter((h) => h % 3 === 0).map((h) => (
          <span key={`h${h}`} className="heatmap__hour num" style={{ '--h': h } as CSSProperties}>
            {String(h).padStart(2, '0')}
          </span>
        ))}
        {data.cells.map((_row, day) => (
          <span key={`d${day}`} className="heatmap__day" style={{ '--d': day } as CSSProperties}>
            {fmt.weekday(day)}
          </span>
        ))}
        {data.cells.map((row, day) =>
          row.map((count, h) => (
            <span
              key={`${day}-${h}`}
              className="heatmap__cell"
              data-level={level(count, data.max)}
              title={cellLabel(day, h, count)}
              style={{ '--d': day, '--h': h } as CSSProperties}
            />
          )),
        )}
        {workingHours &&
          DAYS.map((key, day) => {
            const span = hoursOf(workingHours[key])
            return span ? (
              <span
                key={`w${day}`}
                className="heatmap__open"
                style={{ '--d': day, '--h0': span[0], '--h1': span[1] } as CSSProperties}
              />
            ) : null
          })}
      </div>

      <div className="visually-hidden">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{t('label.day')}</th>
            {HOURS.map((h) => (
              <th key={h} scope="col">
                {hour(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.cells.map((row, day) => (
            <tr key={day}>
              <th scope="row">{fmt.weekday(day)}</th>
              {row.map((count, h) => (
                <td key={h}>{fmt.number(count)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      <div className="heatmap__legend" aria-hidden="true">
        <span>{t('heatmap.fewer')}</span>
        {Array.from({ length: STEPS }, (_, step) => (
          <span key={step} className="heatmap__cell heatmap__swatch" data-level={step + 1} />
        ))}
        <span>{t('heatmap.more')}</span>
        {workingHours && (
          <span className="heatmap__legend-open">
            <span className="heatmap__open-sample" />
            {t('heatmap.workingHours')}
          </span>
        )}
      </div>
    </div>
  )
}
