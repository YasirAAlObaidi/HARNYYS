import type { CSSProperties } from 'react'
import { useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { useInsights } from '../api/queries'
import { type InsightSnapshot, type PeriodData, type PeriodKey, PERIODS } from '../api/types'
import { RankList, SplitBar } from '../components/insights/Bars'
import { Delta, InsightCard, KpiValue } from '../components/insights/Card'
import { type ChartPoint, DailyChart } from '../components/insights/DailyChart'
import { Heatmap } from '../components/insights/Heatmap'
import { useI18n } from '../i18n/context'

/**
 * Page 3: numbers the worker computes at the top of every hour (Dubai time). The page shows the latest
 * snapshot at once and asks again just after the next hour. Staff chats are never in these numbers.
 */
export function InsightsPage() {
  const { t } = useI18n()
  const insights = useInsights()
  const [params, setParams] = useSearchParams()
  const asked = params.get('period') ?? ''
  const period: PeriodKey = (PERIODS as string[]).includes(asked) ? (asked as PeriodKey) : '7d'
  const snapshot = insights.data

  return (
    <div className="insights">
      <header className="page-header insights__head">
        <div className="insights__title">
          <h1 className="page-title">{t('insights.title')}</h1>
          {snapshot && <Freshness snapshot={snapshot} fetchedAt={insights.dataUpdatedAt} />}
        </div>
        <div
          className="segmented"
          role="group"
          aria-label={t('insights.periods')}
          style={{ '--index': PERIODS.indexOf(period), '--count': PERIODS.length } as CSSProperties}
        >
          <span className="segmented__thumb" aria-hidden="true" />
          {PERIODS.map((key) => (
            <button
              key={key}
              type="button"
              className="segmented__option"
              aria-pressed={key === period}
              onClick={() => setParams(key === '7d' ? {} : { period: key }, { replace: true })}
            >
              {t(`period.${key}`)}
            </button>
          ))}
        </div>
      </header>

      {insights.isPending ? (
        <div className="insight-grid" aria-hidden="true">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="card card--span-3 skeleton" style={{ minBlockSize: 128 }} />
          ))}
        </div>
      ) : insights.isError && !snapshot ? (
        <p className="banner banner--danger" role="alert">
          {insights.error instanceof ApiError && insights.error.status === 0 ? t('error.network') : t('error.generic')}
        </p>
      ) : !snapshot ? (
        <p className="banner">{t('insights.none')}</p>
      ) : (
        <Groups data={snapshot.periods[period]} snapshot={snapshot} period={period} />
      )}
    </div>
  )
}

/** "● Updated 14:00 · next 15:00", turning amber, then red, when the hourly run is late. */
function Freshness({ snapshot, fetchedAt }: { snapshot: InsightSnapshot; fetchedAt: number }) {
  const { t, fmt } = useI18n()
  const time = fmt.time(snapshot.computed_at, snapshot.timezone)
  const ageMinutes = (fetchedAt - Date.parse(snapshot.computed_at)) / 60_000
  const state = ageMinutes < 65 ? 'ok' : ageMinutes <= 180 ? 'delayed' : 'stale'
  const text =
    state === 'ok'
      ? t('insights.updated', { time, next: fmt.time(snapshot.next_at, snapshot.timezone) })
      : state === 'delayed'
        ? t('insights.updatedDelayed', { time })
        : t('insights.stale', { hours: fmt.number(Math.floor(ageMinutes / 60)), time })
  return (
    <p className={`freshness freshness--${state}`} role={state === 'ok' ? undefined : 'status'} title={`${snapshot.computed_at} · ${t('insights.tz')}`}>
      <span className="freshness__dot" aria-hidden="true" />
      <span className="num">{text}</span>
    </p>
  )
}

function Groups({ data, snapshot, period }: { data: PeriodData; snapshot: InsightSnapshot; period: PeriodKey }) {
  const { t, fmt, lang } = useI18n()
  const { leads, demand, busy, previous } = data
  const versus = t(`delta.vs.${period}`)
  const productName = (item: { name_en: string | null; name_ar: string | null; code: string }) =>
    (lang === 'ar' ? item.name_ar || item.name_en : item.name_en || item.name_ar) || item.code

  // Today shows messages per hour (the heatmap row for today); other periods show chats per day.
  const today = (new Date(`${data.first_day}T00:00:00Z`).getUTCDay() + 6) % 7
  const perHour: ChartPoint[] | null =
    period === 'today' && busy.heatmap.status !== 'not_tracked'
      ? (busy.heatmap.cells[today] ?? []).map((value, hour) => ({ key: String(hour), label: String(hour).padStart(2, '0'), value }))
      : null

  return (
    <>
      <section className="insight-group" aria-labelledby="group-leads">
        <div className="insight-group__head">
          <h2 id="group-leads" className="insight-group__title">
            {t('group.leads')}
          </h2>
          <p className="insight-group__text">{t('group.leadsText')}</p>
        </div>
        <div className="insight-grid">
          <InsightCard
            span={3}
            title={t('card.newContacts')}
            definition={t('def.newContacts')}
            metric={leads.new_contacts}
            render={(m) => (
              <>
                <KpiValue value={fmt.number(m.value)} />
                <Delta now={m.value} before={previous?.new_contacts} versus={versus} />
              </>
            )}
          />
          <InsightCard
            span={3}
            title={t('card.activeContacts')}
            definition={t('def.active')}
            metric={leads.active_contacts}
            render={(m) => (
              <>
                <KpiValue value={fmt.number(m.value)} />
                <Delta now={m.value} before={previous?.active_contacts} versus={versus} />
              </>
            )}
          />
          <InsightCard span={3} kpi title={t('card.quoteRequests')} metric={leads.quote_requests} render={(m) => <KpiValue value={fmt.number(m.value)} />} />
          <InsightCard span={3} kpi title={t('card.quotesSent')} metric={leads.quotes_sent} render={(m) => <KpiValue value={fmt.number(m.value)} />} />
          <InsightCard
            span={4}
            title={t('card.newVsReturning')}
            metric={leads.new_vs_returning}
            render={(m) => (
              <SplitBar
                parts={[
                  { label: t('label.new'), value: m.new, colour: '--chart-1' },
                  { label: t('label.returning'), value: m.returning, colour: '--chart-2' },
                ]}
              />
            )}
          />
          <InsightCard
            span={8}
            title={t('card.newPerDay')}
            metric={leads.new_contacts_daily}
            render={(m) => (
              <DailyChart
                label={t('card.newContacts')}
                points={m.series.map((d) => ({ key: d.date, label: fmt.day(d.date), value: d.value }))}
              />
            )}
          />
          <InsightCard span={6} kpi title={t('card.lostLeads')} metric={leads.lost_leads} render={(m) => <KpiValue value={fmt.number(m.value)} />} />
          <InsightCard
            span={6}
            title={t('card.lostAtStep')}
            metric={leads.lost_at_step}
            render={(m) => (
              <RankList
                head={t('card.lostAtStep')}
                valueLabel={t('label.times')}
                rows={m.steps.map((s) => ({ key: s.step, label: s.step, value: s.count }))}
              />
            )}
          />
        </div>
      </section>

      <section className="insight-group" aria-labelledby="group-demand">
        <div className="insight-group__head">
          <h2 id="group-demand" className="insight-group__title">
            {t('group.demand')}
          </h2>
          <p className="insight-group__text">{t('group.demandText')}</p>
        </div>
        <div className="insight-grid">
          <InsightCard
            span={6}
            title={t('card.topProducts')}
            metric={demand.top_products}
            note={`${t('note.topProducts')} ${t('stat.lookups', { n: fmt.number(demand.top_products.status !== 'not_tracked' ? demand.top_products.lookups : 0) })}.`}
            render={(m) => (
              <RankList
                head={t('label.product')}
                valueLabel={t('label.chats')}
                rows={m.items.map((item) => ({ key: item.code, label: productName(item), value: item.chats }))}
              />
            )}
          />
          <InsightCard
            span={6}
            title={t('card.notFound')}
            metric={demand.not_found}
            render={(m) => (
              <>
                <dl className="pairs">
                  <div>
                    <dt>{t('label.noMatch')}</dt>
                    <dd className="num">{fmt.number(m.no_match)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.weakMatch')}</dt>
                    <dd className="num">{fmt.number(m.weak_match)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.searches')}</dt>
                    <dd className="num muted">{fmt.number(m.searches)}</dd>
                  </div>
                </dl>
                <RankList
                  head={t('label.search')}
                  valueLabel={t('label.times')}
                  rows={m.top.map((miss) => ({
                    key: `${miss.kind}:${miss.query}`,
                    label: miss.query,
                    value: miss.count,
                    tag: miss.kind === 'weak' ? t('label.weakMatch') : t('label.noMatch'),
                  }))}
                />
              </>
            )}
          />
          <InsightCard
            span={4}
            title={t('card.priceVsStock')}
            metric={demand.price_vs_stock}
            render={(m) => (
              <>
                <dl className="pairs">
                  <div>
                    <dt>{t('label.price')}</dt>
                    <dd className="num">{fmt.number(m.price)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.stock')}</dt>
                    <dd className="num">{fmt.number(m.stock)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.both')}</dt>
                    <dd className="num">{fmt.number(m.both)}</dd>
                  </div>
                </dl>
                <p className="card__caption">{t('stat.of', { total: fmt.number(m.messages) })}</p>
              </>
            )}
          />
          <InsightCard
            span={4}
            title={t('card.languages')}
            metric={demand.languages}
            note={t('note.languages')}
            render={(m) => (
              <>
                <SplitBar
                  parts={[
                    { label: t('label.arabic'), value: m.arabic, colour: '--chart-1' },
                    { label: t('label.english'), value: m.english, colour: '--chart-2' },
                  ]}
                />
                {m.other > 0 && <p className="card__caption">{t('stat.noWords', { n: fmt.number(m.other) })}</p>}
              </>
            )}
          />
          <InsightCard
            span={4}
            title={t('card.voiceNotes')}
            definition={t('def.voice')}
            metric={demand.voice_notes}
            render={(m) => (
              <>
                <KpiValue value={fmt.number(m.count)} />
                <p className="card__caption">
                  {m.messages > 0
                    ? `${t('stat.share', { pct: fmt.percent(m.count / m.messages), total: fmt.number(m.messages) })} · ${t('stat.inChats', { n: fmt.number(m.chats) })}`
                    : t('stat.noData')}
                </p>
                <Delta now={m.count} before={previous?.voice_notes} versus={versus} good="neutral" />
              </>
            )}
          />
        </div>
      </section>

      <section className="insight-group" aria-labelledby="group-busy">
        <div className="insight-group__head">
          <h2 id="group-busy" className="insight-group__title">
            {t('group.busy')}
          </h2>
          <p className="insight-group__text">{t('group.busyText')}</p>
        </div>
        <div className="insight-grid">
          <InsightCard
            span={12}
            title={t('card.heatmap')}
            metric={busy.heatmap}
            render={(m) => <Heatmap data={m} caption={t('card.heatmap')} workingHours={snapshot.working_hours} />}
          />
          <InsightCard
            span={8}
            title={perHour ? t('card.messagesPerHour') : t('card.chatsPerDay')}
            metric={busy.chats_daily}
            render={(m) =>
              perHour ? (
                <DailyChart points={perHour} label={t('label.messages')} />
              ) : (
                <DailyChart
                  label={t('label.chats')}
                  points={m.series.map((d) => ({ key: d.date, label: fmt.day(d.date), value: d.chats }))}
                />
              )
            }
          />
          <InsightCard
            span={4}
            title={t('card.afterHours')}
            definition={t('def.afterHours')}
            metric={busy.after_hours}
            chip={busy.after_hours.status !== 'not_tracked' && !busy.after_hours.hours_confirmed ? t('badge.hoursUnconfirmed') : undefined}
            render={(m) => {
              const share = m.messages > 0 ? m.after_hours / m.messages : 0
              const before =
                previous && previous.after_hours !== null ? (previous.messages > 0 ? previous.after_hours / previous.messages : 0) : null
              return (
                <>
                  <KpiValue value={m.messages > 0 ? fmt.percent(share) : '—'} />
                  <p className="card__caption">{t('stat.share', { pct: fmt.number(m.after_hours), total: fmt.number(m.messages) })}</p>
                  <SplitBar
                    total={m.messages}
                    parts={[
                      { label: t('label.inHours'), value: m.messages - m.after_hours, colour: '--chart-2' },
                      { label: t('label.afterHours'), value: m.after_hours, colour: '--chart-3' },
                    ]}
                  />
                  <Delta now={share} before={before} versus={versus} good="neutral" />
                </>
              )
            }}
          />
          <InsightCard
            span={12}
            title={t('card.lostHeatmap')}
            metric={busy.lost_leads_heatmap}
            render={(m) => <Heatmap data={m} caption={t('card.lostHeatmap')} />}
          />
        </div>
      </section>
    </>
  )
}
