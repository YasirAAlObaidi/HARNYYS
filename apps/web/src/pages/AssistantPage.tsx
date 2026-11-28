import { ArrowUp, Check, Copy, Sparkles } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useRef, useState } from 'react'

import { useAssistant, useSendToAssistant } from '../api/queries'
import type { TranscriptMessage } from '../api/types'
import { useI18n } from '../i18n/context'
import type { MessageKey } from '../i18n/messages'
import { textLang } from '../lib/text'
import { useStickToBottom } from '../lib/useStickToBottom'

const SUGGESTIONS: MessageKey[] = ['assistant.suggest1', 'assistant.suggest2', 'assistant.suggest3', 'assistant.suggest4']

function newClientId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  }
}

/**
 * Page 2: a member of staff chats with the same AI customers reach (same prompt, tools and product table),
 * in one calm column like ChatGPT. The chat is internal: the server keeps it off Chats and out of Insights.
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
  const empty = !history.isPending && messages.length === 0 && !sending
  const { ref, onScroll } = useStickToBottom<HTMLDivElement>(messages.length + (sending ? 1 : 0) + (waiting ? 1 : 0), 'assistant')

  function ask(value: string) {
    const question = value.trim()
    if (!question || send.isPending) return
    setText('')
    setSendFailed(false)
    send.mutate(
      { text: question, client_id: newClientId() },
      {
        onError: () => {
          setText(question)
          setSendFailed(true)
        },
      },
    )
  }

  // The question just sent, shown at once while the server saves it.
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

  const composer = (
    <Composer value={text} onChange={setText} onSend={ask} disabled={send.isPending} failed={sendFailed} />
  )

  return (
    <div className={`assistant${empty ? ' assistant--empty' : ''}`}>
      <header className="assistant__head page-header">
        <h1 className="page-title">{t('assistant.title')}</h1>
        <span className="chip">{t('assistant.internal')}</span>
      </header>

      {empty ? (
        <div className="assistant__welcome">
          <span className="ai-mark ai-mark--lg" aria-hidden="true">
            <Sparkles size={20} strokeWidth={1.5} />
          </span>
          <h2 className="assistant__greeting display">{t('assistant.greeting')}</h2>
          <p className="assistant__greeting-text">{t('assistant.greetingText')}</p>
          {composer}
          <ul className="suggestions">
            {SUGGESTIONS.map((key) => (
              <li key={key}>
                <button type="button" className="suggestion" dir="auto" lang={textLang(t(key))} onClick={() => ask(t(key))}>
                  {t(key)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <>
          <div className="assistant__scroll" ref={ref} onScroll={onScroll}>
            <ol className="turns" aria-live="polite" aria-relevant="additions">
              {history.isPending && (
                <li className="turn" aria-hidden="true">
                  <span className="skeleton" style={{ inlineSize: '60%', blockSize: 16 }} />
                </li>
              )}
              {messages.map((message) => (
                <Turn key={message.id} message={message} />
              ))}
              {optimistic && <Turn message={optimistic} />}
              {waiting && (
                <li className="turn turn--ai">
                  <span className="ai-mark" aria-hidden="true">
                    <Sparkles size={14} strokeWidth={1.5} />
                  </span>
                  <p className="thinking" role="status">
                    <span className="thinking__dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                    {t('assistant.thinking')}
                  </p>
                </li>
              )}
              {noReply && messages.length > 0 && (
                <li className="turn">
                  <p className="banner banner--warning" role="status">
                    {t('assistant.noReply')}
                  </p>
                </li>
              )}
            </ol>
          </div>
          <div className="assistant__dock">{composer}</div>
        </>
      )}
    </div>
  )
}

/** One turn: the staff question as a bubble at the inline end, the AI's answer as plain prose. */
function Turn({ message }: { message: TranscriptMessage }) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  if (message.author === 'customer') {
    return (
      <li className="turn turn--user">
        <article className="turn__question" aria-label={t('author.you')}>
          <p dir="auto" lang={textLang(message.text)}>
            {message.text}
          </p>
        </article>
      </li>
    )
  }
  return (
    <li className="turn turn--ai">
      <span className="ai-mark" aria-hidden="true">
        <Sparkles size={14} strokeWidth={1.5} />
      </span>
      <article className="turn__answer" aria-label={t('author.ai')}>
        <p dir="auto" lang={textLang(message.text)}>
          {message.text}
        </p>
        <div className="turn__actions">
          <button
            type="button"
            className="btn btn--ghost btn--icon turn__action"
            aria-label={copied ? t('assistant.copied') : t('assistant.copy')}
            title={copied ? t('assistant.copied') : t('assistant.copy')}
            onClick={() => {
              void navigator.clipboard?.writeText(message.text).then(() => setCopied(true))
            }}
          >
            {copied ? <Check size={15} strokeWidth={1.5} /> : <Copy size={15} strokeWidth={1.5} />}
          </button>
        </div>
      </article>
    </li>
  )
}

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: (value: string) => void
  disabled: boolean
  failed: boolean
}

function Composer({ value, onChange, onSend, disabled, failed }: ComposerProps) {
  const { t } = useI18n()
  const area = useRef<HTMLTextAreaElement | null>(null)

  function submit(event?: FormEvent) {
    event?.preventDefault()
    onSend(value)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter adds a line. While an input method is composing (Arabic too), Enter is its own.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      {failed && (
        <p className="banner banner--danger" role="alert">
          {t('assistant.sendFailed')}
        </p>
      )}
      <div className="composer__box" onClick={() => area.current?.focus()}>
        <label className="visually-hidden" htmlFor="assistant-input">
          {t('assistant.placeholder')}
        </label>
        <textarea
          ref={area}
          id="assistant-input"
          className="composer__input"
          dir="auto"
          rows={1}
          maxLength={2000}
          placeholder={t('assistant.placeholder')}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="composer__send"
          aria-label={t('assistant.send')}
          title={`${t('assistant.send')} · ${t('assistant.keys')}`}
          disabled={!value.trim() || disabled}
        >
          <ArrowUp size={18} strokeWidth={2} aria-hidden="true" />
        </button>
      </div>
      <p className="composer__hint">{t('assistant.hint')}</p>
    </form>
  )
}
