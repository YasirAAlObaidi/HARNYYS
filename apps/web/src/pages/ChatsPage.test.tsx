import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { ChatSummary, TranscriptMessage } from '../api/types'
import { fakeApi, renderAt, SALES_USER } from '../test/render'

const AHMED: ChatSummary = {
  id: 7,
  channel: 'whatsapp',
  external_user_id: '971501234567',
  customer_name: 'أحمد',
  last_inbound_at: '2026-11-26T09:00:00Z',
  created_at: '2026-11-20T09:00:00Z',
  last_message_at: '2026-11-26T09:00:05Z',
  last_message_text: 'سعر قهوة كولومبيا 135 درهم',
  last_message_author: 'ai',
  message_count: 3,
}
const NO_NAME: ChatSummary = { ...AHMED, id: 8, customer_name: null, external_user_id: '971559876543', last_message_author: 'customer', last_message_text: 'hello' }

const TRANSCRIPT: TranscriptMessage[] = [
  { id: 1, direction: 'in', author: 'customer', text: 'كم سعر قهوة كولومبيا؟', media: [], created_at: '2026-11-26T09:00:00Z', delivery: null },
  { id: 2, direction: 'out', author: 'ai', text: 'سعر قهوة كولومبيا 135 درهم', media: [], created_at: '2026-11-26T09:00:05Z', delivery: 'sent' },
  { id: 3, direction: 'in', author: 'customer', text: '[audio]', media: ['audio'], created_at: '2026-11-26T09:01:00Z', delivery: null },
  { id: 4, direction: 'out', author: 'staff', text: 'I will call you', media: [], created_at: '2026-11-26T09:02:00Z', delivery: 'failed' },
]

function api() {
  return fakeApi({
    'GET /api/auth/me': { user: SALES_USER },
    'GET /api/conversations': (_body: unknown, url: URL) => (url.searchParams.get('q') === 'hello' ? [NO_NAME] : [AHMED, NO_NAME]),
    'GET /api/conversations/7': AHMED,
    'GET /api/conversations/7/messages': TRANSCRIPT,
  })
}

describe('chats', () => {
  it('lists chats by name or number, with the last message and channel', async () => {
    api()
    renderAt('/chats')

    const list = await screen.findByRole('list')
    const items = within(list).getAllByRole('link')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('أحمد')
    expect(items[0]).toHaveTextContent('AI: سعر قهوة كولومبيا 135 درهم')
    expect(items[0]).toHaveTextContent('WhatsApp')
    expect(items[1]).toHaveTextContent('+971559876543')
    expect(screen.getByText('Choose a chat to read it.')).toBeInTheDocument()
  })

  it('searches on the server', async () => {
    const calls = api()
    renderAt('/chats')
    await screen.findAllByRole('link', { name: /أحمد/ })

    await userEvent.type(screen.getByRole('searchbox'), 'hello')

    await waitFor(() => expect(screen.queryByText('أحمد')).not.toBeInTheDocument())
    expect(screen.getByText('+971559876543')).toBeInTheDocument()
    expect(calls.filter((call) => call.path.startsWith('/api/conversations?')).map((call) => call.path)).toEqual([
      '/api/conversations?limit=200',
      '/api/conversations?limit=200&q=hello', // one request after typing stopped, not one per letter
    ])
  })

  it('shows a chat as bubbles: customer, AI and staff look different', async () => {
    api()
    renderAt('/chats/7')

    const customer = await screen.findAllByRole('article', { name: 'Customer' })
    const ai = screen.getByRole('article', { name: 'AI' })
    const staff = screen.getByRole('article', { name: 'Staff' })
    expect(customer[0]).toHaveClass('bubble--customer')
    expect(ai).toHaveClass('bubble--ai')
    expect(staff).toHaveClass('bubble--staff')
    expect(customer[0]!.closest('li')).toHaveClass('bubble-row--start')
    expect(ai.closest('li')).toHaveClass('bubble-row--end')
    // Text keeps its own direction, so Arabic reads right to left even in the English app.
    expect(within(customer[0]!).getByText('كم سعر قهوة كولومبيا؟')).toHaveAttribute('dir', 'auto')
    // A voice note shows as one, not as "[audio]".
    expect(within(customer[1]!).getByText('Voice note')).toBeInTheDocument()
    expect(screen.queryByText('[audio]')).not.toBeInTheDocument()
    expect(within(ai).getByText('Sent')).toBeInTheDocument()
    expect(within(staff).getByText('Not delivered')).toBeInTheDocument()
    expect(screen.getByText('Read-only. The AI answers this chat.')).toBeInTheDocument()
    expect(screen.getByRole('toolbar', { name: 'Chat actions' })).toBeEmptyDOMElement() // room for v2 buttons
  })
})
