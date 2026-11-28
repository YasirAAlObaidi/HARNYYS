import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AssistantHistory } from '../api/types'
import { fakeApi, renderAt, SALES_USER } from '../test/render'

function api(start: AssistantHistory) {
  let history = start
  const calls = fakeApi({
    'GET /api/auth/me': { user: SALES_USER },
    'GET /api/assistant/messages': () => history,
    'POST /api/assistant/messages': (body: unknown) => {
      const { text } = body as { text: string }
      history = {
        messages: [{ id: 10, direction: 'in', author: 'customer', text, media: [], created_at: '2026-11-26T10:00:00Z', delivery: null }],
        pending: true,
      }
      return { queued: true }
    },
  })
  return calls
}

describe('assistant', () => {
  it('greets with suggestions, says it is internal, and sends with a retry-safe id', async () => {
    const calls = api({ messages: [], pending: false })
    renderAt('/assistant')
    expect(await screen.findByRole('heading', { name: 'What do you need to check?' })).toBeInTheDocument()
    expect(screen.getByText(/not shown in Chats or counted in Insights/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'كم سعر قهوة إثيوبيا يرغاتشيفي 250 غرام؟' })).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox'), 'كم سعر الكولومبي؟{Enter}')

    expect(await screen.findByRole('article', { name: 'You' })).toHaveTextContent('كم سعر الكولومبي؟')
    expect(await screen.findByText('Checking prices and stock…')).toBeInTheDocument()
    const sent = calls.find((call) => call.method === 'POST')
    expect(sent?.body).toMatchObject({ text: 'كم سعر الكولومبي؟' })
    expect((sent?.body as { client_id: string }).client_id).toMatch(/.{8,}/)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('a suggestion sends itself', async () => {
    const calls = api({ messages: [], pending: false })
    renderAt('/assistant')

    await userEvent.click(await screen.findByRole('button', { name: 'Which espresso machines do we sell?' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({ text: 'Which espresso machines do we sell?' })
  })

  it('shows the question at the inline end and the answer as prose', async () => {
    api({
      pending: false,
      messages: [
        { id: 1, direction: 'in', author: 'customer', text: 'price?', media: [], created_at: '2026-11-26T10:00:00Z', delivery: null },
        { id: 2, direction: 'out', author: 'ai', text: '135 AED', media: [], created_at: '2026-11-26T10:00:04Z', delivery: 'sent' },
      ],
    })
    renderAt('/assistant')

    const answer = await screen.findByRole('article', { name: 'Kahraman AI' })
    expect(answer).toHaveTextContent('135 AED')
    expect(answer.closest('li')).toHaveClass('turn--ai')
    expect(screen.getByRole('article', { name: 'You' }).closest('li')).toHaveClass('turn--user')
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Checking prices and stock…')).not.toBeInTheDocument())
  })
})
