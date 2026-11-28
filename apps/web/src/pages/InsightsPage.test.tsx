import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { InsightSnapshot } from '../api/types'
import { writeSetting } from '../lib/storage'
// Written by the server's own maths (apps/server/tests/test_insights.py), so this is the real format.
import fixture from '../test/insights-snapshot.json'
import { fakeApi, renderAt, SALES_USER } from '../test/render'

const snapshot = fixture as unknown as InsightSnapshot

function card(title: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: title, level: 3 })
  return heading.closest('article') as HTMLElement
}

describe('insights', () => {
  it('shows when the numbers were computed and when the next ones come, in Dubai time', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/insights': { snapshot } })
    renderAt('/insights')

    expect(await screen.findByText('Updated 14:00 · next 15:00')).toBeInTheDocument()
  })

  it('never shows a number for a metric that is not tracked yet', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/insights': { snapshot } })
    renderAt('/insights')
    await screen.findByText('Updated 14:00 · next 15:00')

    for (const title of ['Quote requests', 'Quotes sent', 'Lost leads', 'Where leads were lost', 'Lost leads by day and hour']) {
      const box = card(title)
      expect(within(box).getByText('Not tracked yet')).toBeInTheDocument()
      expect(box).toHaveTextContent(/Needs a/)
      expect(box.textContent).not.toMatch(/\d/)
    }
  })

  it('shows the live numbers of the chosen period, and labels estimates', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/insights': { snapshot } })
    renderAt('/insights')
    await screen.findByText('Updated 14:00 · next 15:00')

    // 7 days is the default period.
    expect(screen.getByRole('button', { name: '7 days' })).toHaveAttribute('aria-pressed', 'true')
    expect(card('New contacts')).toHaveTextContent('3')
    expect(card('New vs returning')).toHaveTextContent(/New\s*3/)
    expect(card('New vs returning')).toHaveTextContent(/Returning\s*1/)
    expect(card('Most-asked products')).toHaveTextContent('Colombia Supremo 1 kg')
    expect(card('Items we could not find')).toHaveTextContent('chemex')
    expect(within(card('Price vs stock questions')).getByText('Estimate')).toBeInTheDocument()
    expect(card('After-hours messages')).toHaveTextContent('67%')
    expect(within(card('After-hours messages')).getByText('Working hours not confirmed')).toBeInTheDocument()
    expect(card('Voice notes')).toHaveTextContent('1')
    expect(screen.getByRole('table', { name: 'Messages by day and hour' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Today' }))
    expect(card('New contacts')).toHaveTextContent('2')
  })

  it('says so when there is no snapshot yet', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/insights': { snapshot: null } })
    renderAt('/insights')

    expect(await screen.findByText(/No numbers yet/)).toBeInTheDocument()
  })

  it('reads right to left in Arabic, with Western digits', async () => {
    writeSetting('yyai.lang', 'ar')
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/insights': { snapshot } })
    renderAt('/insights')

    expect(await screen.findByText('آخر تحديث 14:00 · التحديث التالي 15:00')).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('dir', 'rtl')
    expect(document.documentElement).toHaveAttribute('lang', 'ar')
    expect(within(card('طلبات عروض الأسعار')).getByText('غير مُتتبَّع بعد')).toBeInTheDocument()
  })
})
