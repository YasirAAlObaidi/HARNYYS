import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AssistantHistory } from '../api/types'
import { fakeApi, renderAt, SALES_USER } from '../test/render'

describe('assistant', () => {
  it('sends a question with a retry-safe id and shows the AI writing until the reply arrives', async () => {
    let history: AssistantHistory = { messages: [], pending: false }
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
    renderAt('/assistant')
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument()
    expect(screen.getByText(/Internal chat/)).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox'), 'كم سعر الكولومبي؟{Enter}')

    expect(await screen.findByRole('article', { name: 'You' })).toHaveTextContent('كم سعر الكولومبي؟')
    expect(await screen.findByText('The AI is writing…')).toBeInTheDocument()
    const sent = calls.find((call) => call.method === 'POST')
    expect(sent?.body).toMatchObject({ text: 'كم سعر الكولومبي؟' })
    expect((sent?.body as { client_id: string }).client_id).toMatch(/.{8,}/)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('shows the reply on the AI side', async () => {
    fakeApi({
      'GET /api/auth/me': { user: SALES_USER },
      'GET /api/assistant/messages': {
        pending: false,
        messages: [
          { id: 1, direction: 'in', author: 'customer', text: 'price?', media: [], created_at: '2026-11-26T10:00:00Z', delivery: null },
          { id: 2, direction: 'out', author: 'ai', text: '135 AED', media: [], created_at: '2026-11-26T10:00:04Z', delivery: 'sent' },
        ],
      },
    })
    renderAt('/assistant')

    const reply = await screen.findByRole('article', { name: 'AI' })
    expect(reply.closest('li')).toHaveClass('bubble-row--start')
    expect(screen.getByRole('article', { name: 'You' }).closest('li')).toHaveClass('bubble-row--end')
    await waitFor(() => expect(screen.queryByText('The AI is writing…')).not.toBeInTheDocument())
  })
})
