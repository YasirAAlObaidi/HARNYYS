import { Check, CircleAlert, Clock, Mic, Paperclip, Sparkles } from 'lucide-react'

import type { Author, TranscriptMessage } from '../api/types'
import { useI18n } from '../i18n/context'
import type { MessageKey } from '../i18n/messages'
import { MEDIA_PLACEHOLDER, textLang } from '../lib/text'

const MEDIA_KINDS = ['audio', 'image', 'video', 'document', 'sticker'] as const
const ICON = { size: 14, strokeWidth: 1.5, 'aria-hidden': true } as const

function mediaLabel(kind: string): MessageKey {
  return (MEDIA_KINDS as readonly string[]).includes(kind) ? (`media.${kind}` as MessageKey) : 'media.other'
}

export interface BubbleProps {
  message: TranscriptMessage
  /** Who wrote it: the accessible name of the bubble, and shown above the first bubble of a run. */
  label: string
  /** "start" is the left in English and the right in Arabic. */
  side: 'start' | 'end'
  /** Colours: customer (plain), AI (amber tint), staff (green tint). */
  tone: Author
  /** The first bubble of a run from one speaker: shows the label and the tail corner. */
  first?: boolean
  showDelivery?: boolean
}

/** One chat message. Text keeps its own direction (dir="auto") and language, so mixed chats read right. */
export function MessageBubble({ message, label, side, tone, first = true, showDelivery = false }: BubbleProps) {
  const { t, fmt } = useI18n()
  const placeholderOnly = message.media.length > 0 && MEDIA_PLACEHOLDER.test(message.text.trim())

  return (
    <li className={`bubble-row bubble-row--${side}${first ? ' bubble-row--first' : ''}`}>
      <article className={`bubble bubble--${tone}`} aria-label={label}>
        {first && tone !== 'customer' && (
          <header className="bubble__author">
            {tone === 'ai' && <Sparkles {...ICON} />}
            {label}
          </header>
        )}
        {message.media.map((kind, index) => (
          <p key={`${kind}-${index}`} className="bubble__media">
            {kind === 'audio' ? <Mic {...ICON} /> : <Paperclip {...ICON} />}
            {t(mediaLabel(kind))}
          </p>
        ))}
        {!placeholderOnly && (
          <p className="bubble__text" dir="auto" lang={textLang(message.text)}>
            {message.text}
          </p>
        )}
        <footer className="bubble__meta">
          <time dateTime={message.created_at} className="num">
            {fmt.time(message.created_at)}
          </time>
          {showDelivery && message.delivery && <Delivery status={message.delivery} />}
        </footer>
      </article>
    </li>
  )
}

/** Sent, sending, failed or waiting for approval: an icon plus the words (for screen readers, or shown). */
function Delivery({ status }: { status: string }) {
  const { t } = useI18n()
  if (status === 'failed') {
    return (
      <span className="delivery delivery--failed">
        <CircleAlert {...ICON} />
        {t('delivery.failed')}
      </span>
    )
  }
  if (status === 'awaiting_approval') return <span className="chip chip--warning">{t('delivery.awaiting_approval')}</span>
  const key = status === 'sent' ? 'delivery.sent' : status === 'pending' || status === 'sending' ? 'delivery.pending' : null
  if (!key) return null
  return (
    <span className="delivery" title={t(key)}>
      {status === 'sent' ? <Check {...ICON} /> : <Clock {...ICON} />}
      <span className="visually-hidden">{t(key)}</span>
    </span>
  )
}
