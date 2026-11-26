import { useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { useInsights } from '../api/queries'
import { type InsightSnapshot, type PeriodData, type PeriodKey, PERIODS } from '../api/types'
import { RankList, SplitBar } from '../components/insights/Bars'
import { BigNumber, InsightCard } from '../components/insights/Card'
import { DailyChart } from '../components/insights/DailyChart'
import { Heatmap } from '../components/insights/Heatmap'
import { useI18n } from '../i18n/context'

const LATE_AFTER_MS = 5 * 60_000 // a snapshot still not replaced five minutes after the hour is late

/**
 * Page 3: numbers the worker computes at the top of every hour (Asia/Dubai). The page shows the latest
 * snapshot at once and asks again just after the next hour. Staff chats are never in these numbers.
 */
export function InsightsPage() {
  const { t, fmt } = useI18n()
  const insights = useInsights()
  const [params, setParams] = useSearchParams()
  const period: PeriodKey = (PERIODS as string[]).includes(params.get('period') ?? '') ? (params.get('period') as PeriodKey) : '7d'
  const snapshot = insights.data

  return (
    <div className="insights">
      <header className="insights__head">
        <div>
          <h1 className="page-title">{t('insights.title')}</h1>
          {snapshot && (
            <p className="insights__updated">
              {t('insights.updated', {
                time: fmt.time(snapshot.computed_at, snapshot.timezone),
                next: fmt.time(snapshot.next_at, snapshot.timezone),
              })}
            </p>
          )}
        </div>
        <div className="segmented" role="group" aria-label={t('insights.periods')}>
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
        <p className="muted">{t('loading')}</p>
      ) : insights.isError && !snapshot ? (
        <p className="form-error" role="alert">
          {insights.error instanceof ApiError && insights.error.status === 0 ? t('error.network') : t('error.generic')}
        </p>
      ) : !snapshot ? (
        <p className="notice">{t('insights.none')}</p>
      ) : (
        <>
          {insights.dataUpdatedAt > Date.parse(snapshot.next_at) + LATE_AFTER_MS && (
            <p className="notice notice--warning" role="status">
              {t('insights.late')}
            </p>
          )}
          <Groups data={snapshot.periods[period]} snapshot={snapshot} />
        </>
      )}
    </div>
  )
}

function Groups({ data, snapshot }: { data: PeriodData; snapshot: InsightSnapshot }) {
  const { t, fmt, lang } = useI18n()
  const { leads, demand, busy } = data
  const productName = (item: { name_en: string | null; name_ar: string | null; code: string }) =>
    (lang === 'ar' ? item.name_ar || item.name_en : item.name_en || item.name_ar) || item.code

  return (
    <>
      <section className="insight-group" aria-labelledby="group-leads">
        <h2 id="group-leads" className="insight-group__title">
          {t('group.leads')}
        </h2>
        <div className="cards">
          <InsightCard
            title={t('card.newContacts')}
            metric={leads.new_contacts}
            render={(m) => <BigNumber value={fmt.number(m.value)} />}
          />
          <InsightCard
            title={t('card.activeContacts')}
            metric={leads.active_contacts}
            render={(m) => <BigNumber value={fmt.number(m.value)} />}
          />
          <InsightCard
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
            title={t('card.newPerDay')}
            metric={leads.new_contacts_daily}
            wide
            render={(m) => <DailyChart points={m.series} label={t('card.newContacts')} />}
          />
          <InsightCard title={t('card.quoteRequests')} metric={leads.quote_requests} render={(m) => <BigNumber value={fmt.number(m.value)} />} />
          <InsightCard title={t('card.quotesSent')} metric={leads.quotes_sent} render={(m) => <BigNumber value={fmt.number(m.value)} />} />
          <InsightCard title={t('card.lostLeads')} metric={leads.lost_leads} render={(m) => <BigNumber value={fmt.number(m.value)} />} />
          <InsightCard
            title={t('card.lostAtStep')}
            metric={leads.lost_at_step}
            render={(m) => (
              <RankList rows={m.steps.map((s) => ({ key: s.step, label: s.step, value: s.count }))} valueLabel={t('label.times')} />
            )}
          />
        </div>
      </section>

      <section className="insight-group" aria-labelledby="group-demand">
        <h2 id="group-demand" className="insight-group__title">
          {t('group.demand')}
        </h2>
        <div className="cards">
          <InsightCard
            title={t('card.topProducts')}
            metric={demand.top_products}
            wide
            note={t('note.topProducts')}
            render={(m) => (
              <>
                <RankList
                  valueLabel={t('label.chats')}
                  rows={m.items.map((item) => ({
                    key: item.code,
                    label: productName(item),
                    value: item.chats,
                    detail: `${t('label.asked')} ${fmt.number(item.asks)}`,
                  }))}
                />
                <p className="muted small">{t('stat.lookups', { n: fmt.number(m.lookups) })}</p>
              </>
            )}
          />
          <InsightCard
            title={t('card.priceVsStock')}
            metric={demand.price_vs_stock}
            render={(m) => (
              <>
                <dl className="pairs">
                  <div>
                    <dt>{t('label.price')}</dt>
                    <dd>{fmt.number(m.price)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.stock')}</dt>
                    <dd>{fmt.number(m.stock)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.both')}</dt>
                    <dd>{fmt.number(m.both)}</dd>
                  </div>
                </dl>
                <p className="muted small">{t('stat.of', { total: fmt.number(m.messages) })}</p>
              </>
            )}
          />
          <InsightCard
            title={t('card.notFound')}
            metric={demand.not_found}
            wide
            render={(m) => (
              <>
                <dl className="pairs">
                  <div>
                    <dt>{t('label.noMatch')}</dt>
                    <dd>{fmt.number(m.no_match)}</dd>
                  </div>
                  <div>
                    <dt>{t('label.weakMatch')}</dt>
                    <dd>{fmt.number(m.weak_match)}</dd>
                  </div>
                </dl>
                <p className="muted small">
                  {t('stat.searches', { n: fmt.number(m.no_match + m.weak_match), total: fmt.number(m.searches) })}
                </p>
                <RankList
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
            title={t('card.languages')}
            metric={demand.languages}
            note={t('note.languages')}
            render={(m) => (
              <SplitBar
                parts={[
                  { label: t('label.arabic'), value: m.arabic, colour: '--chart-1' },
                  { label: t('label.english'), value: m.english, colour: '--chart-2' },
                  { label: t('label.other'), value: m.other, colour: '--chart-3' },
                ]}
              />
            )}
          />
          <InsightCard
            title={t('card.voiceNotes')}
            metric={demand.voice_notes}
            render={(m) => (
              <BigNumber
                value={fmt.number(m.count)}
                caption={
                  m.messages > 0
                    ? `${t('stat.share', { pct: fmt.percent(m.count / m.messages), total: fmt.number(m.messages) })} · ${t('stat.inChats', { n: fmt.number(m.chats) })}`
                    : t('stat.noData')
                }
              />
            )}
          />
        </div>
      </section>

      <section className="insight-group" aria-labelledby="group-busy">
        <h2 id="group-busy" className="insight-group__title">
          {t('group.busy')}
        </h2>
        <div className="cards">
          <InsightCard
            title={t('card.heatmap')}
            metric={busy.heatmap}
            wide
            note={snapshot.timezone}
            render={(m) => <Heatmap data={m} caption={t('card.heatmap')} />}
          />
          <InsightCard
            title={t('card.chatsPerDay')}
            metric={busy.chats_daily}
            wide
            render={(m) => <DailyChart points={m.series.map((d) => ({ date: d.date, value: d.chats }))} label={t('label.chats')} />}
          />
          <InsightCard
            title={t('card.afterHours')}
            metric={busy.after_hours}
            note={t('note.afterHours')}
            badge={busy.after_hours.status !== 'not_tracked' && !busy.after_hours.hours_confirmed ? t('badge.hoursUnconfirmed') : undefined}
            render={(m) => (
              <BigNumber
                value={m.messages > 0 ? fmt.percent(m.after_hours / m.messages) : '–'}
                caption={t('stat.share', { pct: fmt.number(m.after_hours), total: fmt.number(m.messages) })}
              />
            )}
          />
          <InsightCard
            title={t('card.lostHeatmap')}
            metric={busy.lost_leads_heatmap}
            render={(m) => <Heatmap data={m} caption={t('card.lostHeatmap')} />}
          />
        </div>
      </section>
    </>
  )
}
