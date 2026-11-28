import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { useI18n } from '../../i18n/context'

export interface ChartPoint {
  key: string
  /** The axis label: "26 Nov" for a day, "14" for an hour. */
  label: string
  value: number
}

/**
 * Columns: one per day (or per hour for Today). Colours come from the theme tokens, so it reads in light and
 * dark. The SVG is drawn left to right; in Arabic the time axis is reversed and the number axis moves to
 * the right, so time runs from right to left like the rest of the page. No draw-in animation on refresh.
 */
export function DailyChart({ points, label }: { points: ChartPoint[]; label: string }) {
  const { dir, fmt } = useI18n()
  const rtl = dir === 'rtl'
  const summary = points.map((point) => `${point.label}: ${fmt.number(point.value)}`).join(', ')
  const max = Math.max(...points.map((point) => point.value), 0)

  return (
    <figure className="chart" aria-label={`${label}. ${summary}`}>
      <div className="chart__canvas" dir="ltr">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={points} margin={{ top: 8, right: 4, bottom: 0, left: 4 }} barCategoryGap="22%">
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis
              dataKey="label"
              reversed={rtl}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              minTickGap={14}
            />
            <YAxis
              orientation={rtl ? 'right' : 'left'}
              allowDecimals={false}
              tickCount={4}
              domain={[0, max > 0 ? 'auto' : 4]}
              width={32}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              tickFormatter={(value: number) => fmt.number(value)}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: 'var(--bg-hover)' }}
              formatter={(value) => [fmt.number(Number(value)), label]}
              contentStyle={{
                background: 'var(--bg-overlay)',
                border: '1px solid var(--border-default)',
                borderRadius: 8,
                boxShadow: 'var(--shadow-md)',
                color: 'var(--text-primary)',
                fontSize: 12,
                direction: dir,
              }}
              labelStyle={{ color: 'var(--text-muted)' }}
              itemStyle={{ color: 'var(--text-primary)' }}
            />
            <Bar dataKey="value" name={label} fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
