import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { useI18n } from '../../i18n/context'

export interface DailyPoint {
  date: string
  value: number
}

/**
 * A bar per day. Colours come from the theme tokens (CSS variables), so it reads in light and dark.
 * The SVG is drawn left to right; in Arabic the day axis is reversed and the number axis moves to the right,
 * so time runs from right to left like the rest of the page.
 */
export function DailyChart({ points, label }: { points: DailyPoint[]; label: string }) {
  const { dir, fmt } = useI18n()
  const rtl = dir === 'rtl'
  const data = points.map((point) => ({ ...point, day: fmt.day(point.date) }))
  const summary = points.map((point) => `${fmt.day(point.date)}: ${fmt.number(point.value)}`).join(', ')

  return (
    <figure className="chart" aria-label={`${label}. ${summary}`}>
      <div className="chart__canvas" dir="ltr">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="day"
              reversed={rtl}
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-strong)' }}
              interval="preserveStartEnd"
              minTickGap={12}
            />
            <YAxis
              orientation={rtl ? 'right' : 'left'}
              allowDecimals={false}
              width={36}
              tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
              tickFormatter={(value: number) => fmt.number(value)}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: 'var(--surface-2)' }}
              formatter={(value) => [fmt.number(Number(value)), label]}
              contentStyle={{
                background: 'var(--surface)',
                border: '1px solid var(--border-strong)',
                borderRadius: 6,
                color: 'var(--text)',
                direction: dir,
              }}
              labelStyle={{ color: 'var(--text-muted)' }}
              itemStyle={{ color: 'var(--text)' }}
            />
            <Bar dataKey="value" name={label} fill="var(--chart-1)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
