import { type FormEvent, type KeyboardEvent, useState } from 'react'

import { useAssistant, useSendToAssistant } from '../api/queries'
import type { TranscriptMessage } from '../api/types'
import { SendIcon } from '../components/icons'
import { MessageBubble } from '../components/MessageBubble'
import { useI18n } from '../i18n/context'
import { useStickToBottom } from '../lib/useStickToBottom'

function newClientId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  }
}

/**
 * Page 2: a member of staff chats with the same AI customers reach (same prompt, tools and product table).
 * The chat is internal: the server keeps it off the Chats page and out of Insights.
 */
export function AssistantPage() {
  const { t } = useI18n()
  const history = useAssistant()
  const send = useSendToAssistant()
  const [text, setText] = useState('')
  const [sendFailed, setSendFailed] = useState(false)

  const messages = history.data?.messages ?? []
  const sending = send.isPending ? send.variables : undefined
  const waiting = Boolean(history.data?.pending) || send.isPending
  const last = messages.at(-1)
  const noReply = !waiting && last?.author === 'customer'
  const { ref, onScroll } = useStickToBottom<HTMLOListElement>(messages.length + (sending ? 1 : 0) + (waiting ? 1 : 0), 'assistant')

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const value = text.trim()
    if (!value || send.isPending) return
    setText('')
    setSendFailed(false)
    send.mutate(
      { text: value, client_id: newClientId() },
      {
        onError: () => {
          setText(value)
          setSendFailed(true)
        },
      },
    )
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter adds a line. While an Arabic (or any) input method is composing, Enter is its own.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  // The message just sent, shown at once while the server saves it.
  const optimistic: TranscriptMessage | null = sending
    ? {
        id: -1,
        direction: 'in',
        author: 'customer',
        text: sending.text,
        media: [],
        created_at: new Date(send.submittedAt).toISOString(),
        delivery: null,
      }
    : null

  return (
    <div className="assistant">
      <header className="assistant__head">
        <h1 className="page-title">{t('assistant.title')}</h1>
        <p className="muted">{t('assistant.intro')}</p>
        <p className="notice notice--internal">{t('assistant.internal')}</p>
      </header>

      <ol className="bubbles assistant__messages" ref={ref} onScroll={onScroll} aria-live="polite" aria-relevant="additions">
        {history.isPending ? (
          <li className="muted pad">{t('loading')}</li>
        ) : messages.length === 0 && !optimistic ? (
          <li className="muted pad">{t('assistant.empty')}</li>
        ) : null}
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            label={message.author === 'customer' ? t('author.you') : t('author.ai')}
            tone={message.author === 'customer' ? 'staff' : 'ai'}
            side={message.author === 'customer' ? 'end' : 'start'}
          />
        ))}
        {optimistic && <MessageBubble message={optimistic} label={t('author.you')} tone="staff" side="end" />}
        {waiting && (
          <li className="bubble-row bubble-row--start">
            <p className="typing" role="status">
              <span className="typing__dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              {t('assistant.thinking')}
            </p>
          </li>
        )}
        {noReply && messages.length > 0 && (
          <li className="muted pad" role="status">
            {t('assistant.noReply')}
          </li>
        )}
      </ol>

      <form className="composer" onSubmit={submit}>
        {sendFailed && (
          <p className="form-error" role="alert">
            {t('assistant.sendFailed')}
          </p>
        )}
        <div className="composer__row">
          <label className="visually-hidden" htmlFor="assistant-input">
            {t('assistant.placeholder')}
          </label>
          <textarea
            id="assistant-input"
            className="composer__input"
            dir="auto"
            rows={2}
            maxLength={2000}
            placeholder={t('assistant.placeholder')}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <button type="submit" className="button button--primary composer__send" disabled={!text.trim() || send.isPending}>
            <SendIcon />
            <span>{t('assistant.send')}</span>
          </button>
        </div>
        <p className="composer__hint muted">{t('assistant.hint')}</p>
      </form>
    </div>
  )
}
