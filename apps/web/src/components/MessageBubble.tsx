import type { Author, TranscriptMessage } from '../api/types'
import { useI18n } from '../i18n/context'
import type { MessageKey } from '../i18n/messages'
import { MicIcon, PaperclipIcon } from './icons'

const MEDIA_KINDS = ['audio', 'image', 'video', 'document', 'sticker'] as const
const PLACEHOLDER = /^\[[a-z ]+(: [a-z_]+)?\]$/ // what the WhatsApp handler stores for media without a caption

function mediaLabel(kind: string): MessageKey {
  return (MEDIA_KINDS as readonly string[]).includes(kind) ? (`media.${kind}` as MessageKey) : 'media.other'
}

function deliveryLabel(delivery: string): MessageKey | null {
  const known = ['pending', 'sending', 'sent', 'failed', 'awaiting_approval']
  return known.includes(delivery) ? (`delivery.${delivery}` as MessageKey) : null
}

export interface BubbleProps {
  message: TranscriptMessage
  /** Who wrote it, as shown above the text. */
  label: string
  /** Which side of the column it sits on: "end" is the right in English and the left in Arabic. */
  side: 'start' | 'end'
  /** Colours: customer, AI or staff. */
  tone: Author
  showDelivery?: boolean
}

/** One chat message. Text keeps its own direction (dir="auto"), so Arabic and English both read right. */
export function MessageBubble({ message, label, side, tone, showDelivery = false }: BubbleProps) {
  const { t, fmt } = useI18n()
  const placeholderOnly = message.media.length > 0 && PLACEHOLDER.test(message.text.trim())
  const delivery = showDelivery && message.delivery ? deliveryLabel(message.delivery) : null

  return (
    <li className={`bubble-row bubble-row--${side}`}>
      <article className={`bubble bubble--${tone}`} aria-label={label}>
        <header className="bubble__author">{label}</header>
        {message.media.map((kind, index) => (
          <p key={`${kind}-${index}`} className="bubble__media">
            {kind === 'audio' ? <MicIcon width={16} height={16} /> : <PaperclipIcon width={16} height={16} />}
            {t(mediaLabel(kind))}
          </p>
        ))}
        {!placeholderOnly && (
          <p className="bubble__text" dir="auto">
            {message.text}
          </p>
        )}
        <footer className="bubble__meta">
          <time dateTime={message.created_at}>{fmt.time(message.created_at)}</time>
          {delivery && (
            <span className={`bubble__delivery bubble__delivery--${message.delivery}`}>{t(delivery)}</span>
          )}
        </footer>
      </article>
    </li>
  )
}
