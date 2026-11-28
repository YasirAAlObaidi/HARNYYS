import { ChevronLeft, Lock, MessageCircle, MessagesSquare, Mic, Phone, Search } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useChat, useChats, useTranscript } from '../api/queries'
import type { ChatSummary, TranscriptMessage } from '../api/types'
import mark from '../assets/kahraman-mark.svg'
import { MessageBubble } from '../components/MessageBubble'
import { useI18n } from '../i18n/context'
import type { MessageKey } from '../i18n/messages'
import { displayName, formatNumber, initial } from '../lib/people'
import { MEDIA_PLACEHOLDER, textLang } from '../lib/text'
import { useDebounced } from '../lib/useDebounced'
import { useStickToBottom } from '../lib/useStickToBottom'

const ICON = { size: 16, strokeWidth: 1.5, 'aria-hidden': true } as const

/**
 * Page 1: every customer chat the AI is handling, read-only for now. The list sits at the inline start and
 * the open chat beside it; on a phone one shows at a time. Later status chips go in `chat-row__chips`, and
 * actions (pause the AI, take over, quote request) in the `transcript__actions` toolbar.
 */
export function ChatsPage() {
  const params = useParams()
  const id = params.id && /^\d+$/.test(params.id) ? Number(params.id) : null

  return (
    <div className={`chats ${id === null ? 'chats--list' : 'chats--open'}`}>
      <ChatList selected={id} />
      {id === null ? <NothingSelected /> : <Transcript key={id} id={id} />}
    </div>
  )
}

function channelLabel(channel: string, t: (key: MessageKey) => string): string {
  return channel === 'whatsapp' ? t('channel.whatsapp') : channel
}

function ChatList({ selected }: { selected: number | null }) {
  const { t, fmt } = useI18n()
  const [search, setSearch] = useState('')
  const query = useDebounced(search, 300)
  const chats = useChats(query)
  const input = useRef<HTMLInputElement | null>(null)

  // "/" jumps to the search box, as in most inbox tools.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(target.tagName)) {
        event.preventDefault()
        input.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const groups = new Map<string, ChatSummary[]>()
  for (const chat of chats.data ?? []) {
    const last = chat.last_message_at ?? chat.last_inbound_at ?? chat.created_at
    const label = fmt.dayLabel(last)
    const key = label === t('time.today') || label === t('time.yesterday') ? label : t('chats.earlier')
    groups.set(key, [...(groups.get(key) ?? []), chat])
  }

  return (
    <section className="chat-list" aria-label={t('chats.title')}>
      <header className="chat-list__head">
        <div className="chat-list__title">
          <h1 className="page-title">{t('chats.title')}</h1>
          {chats.data && <span className="chat-list__count num">{fmt.number(chats.data.length)}</span>}
        </div>
        <label className="search">
          <Search {...ICON} className="search__icon" />
          <span className="visually-hidden">{t('chats.search')}</span>
          <input
            ref={input}
            type="search"
            className="input search__input"
            placeholder={t('chats.search')}
            dir="auto"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <kbd className="search__key" aria-hidden="true">
            /
          </kbd>
        </label>
      </header>

      <div className="chat-list__body">
        {chats.isError && (
          <p className="banner banner--danger chat-list__error" role="alert">
            {chats.error instanceof ApiError && chats.error.status === 0 ? t('error.network') : t('chats.loadError')}{' '}
            <button type="button" className="link-button" onClick={() => chats.refetch()}>
              {t('retry')}
            </button>
          </p>
        )}
        {chats.isPending ? (
          <ul className="chat-list__items" aria-hidden="true">
            {Array.from({ length: 8 }, (_, index) => (
              <li key={index} className="chat-row chat-row--skeleton">
                <span className="avatar skeleton" />
                <span className="chat-row__body">
                  <span className="skeleton" style={{ inlineSize: '55%', blockSize: 12 }} />
                  <span className="skeleton" style={{ inlineSize: '85%', blockSize: 10 }} />
                </span>
              </li>
            ))}
          </ul>
        ) : !chats.data || chats.data.length === 0 ? (
          query.trim() ? (
            <div className="empty">
              <p className="empty__text">{t('chats.noResults', { q: query.trim() })}</p>
              <button type="button" className="btn" onClick={() => setSearch('')}>
                {t('chats.clear')}
              </button>
            </div>
          ) : (
            <div className="empty">
              <span className="empty__icon">
                <MessagesSquare size={18} strokeWidth={1.5} aria-hidden="true" />
              </span>
              <p className="empty__title display">{t('chats.empty')}</p>
              <p className="empty__text">{t('chats.emptyText')}</p>
            </div>
          )
        ) : (
          [...groups].map(([label, items]) => (
            <Fragment key={label}>
              <h2 className="chat-list__group">{label}</h2>
              <ul className="chat-list__items">
                {items.map((chat) => (
                  <li key={chat.id}>
                    <ChatRow chat={chat} selected={chat.id === selected} />
                  </li>
                ))}
              </ul>
            </Fragment>
          ))
        )}
      </div>
    </section>
  )
}

function ChatRow({ chat, selected }: { chat: ChatSummary; selected: boolean }) {
  const { t, fmt } = useI18n()
  const name = displayName(chat)
  const last = chat.last_message_at ?? chat.last_inbound_at ?? chat.created_at
  const text = chat.last_message_text ?? ''
  const voice = MEDIA_PLACEHOLDER.test(text.trim()) && text.includes('audio')
  const who = chat.last_message_author === 'ai' ? t('preview.ai') : chat.last_message_author === 'staff' ? t('preview.staff') : ''
  return (
    <NavLink
      to={`/chats/${chat.id}`}
      className={`chat-row${selected ? ' chat-row--selected' : ''}`}
      aria-current={selected ? 'page' : undefined}
    >
      <span className="chat-row__avatar">
        <span className="avatar" data-tint={chat.id % 6} aria-hidden="true">
          {chat.customer_name?.trim() ? initial(name) : <Phone size={15} strokeWidth={1.5} />}
        </span>
        <span className="chat-row__channel" title={channelLabel(chat.channel, t)}>
          <MessageCircle size={10} strokeWidth={2} aria-hidden="true" />
        </span>
      </span>
      <span className="chat-row__body">
        <span className="chat-row__top">
          <span className="chat-row__name" dir="auto">
            {name}
          </span>
          <time className="chat-row__time num" dateTime={last}>
            {fmt.when(last)}
          </time>
        </span>
        <span className="chat-row__preview">
          {who && <span className="chat-row__who">{who}</span>}
          {voice ? (
            <span className="chat-row__text">
              <Mic size={13} strokeWidth={1.5} aria-hidden="true" /> {t('media.audio')}
            </span>
          ) : (
            <span className="chat-row__text" dir="auto" lang={textLang(text)}>
              {text}
            </span>
          )}
        </span>
        <span className="chat-row__chips">
          <span className="visually-hidden">{channelLabel(chat.channel, t)}</span>
          {/* Later: up to two status chips, e.g. "AI paused", "Handover", "Quote". */}
        </span>
      </span>
    </NavLink>
  )
}

function NothingSelected() {
  const { t } = useI18n()
  return (
    <section className="transcript transcript--empty">
      <img src={mark} alt="" className="transcript__watermark" width="120" height="120" />
      <div className="empty">
        <p className="empty__title display">{t('chats.select')}</p>
        <p className="empty__text">{t('chats.selectText')}</p>
      </div>
    </section>
  )
}

function Transcript({ id }: { id: number }) {
  const { t, fmt } = useI18n()
  const chat = useChat(id)
  const messages = useTranscript(id)
  const list = messages.data ?? []
  const { ref, onScroll } = useStickToBottom<HTMLDivElement>(list.length, id)
  const missing = chat.error instanceof ApiError && chat.error.status === 404
  const name = chat.data ? displayName(chat.data) : ''

  return (
    <section className="transcript" aria-labelledby="transcript-title">
      <header className="transcript__header">
        <Link to="/chats" className="btn btn--ghost btn--icon transcript__back" aria-label={t('chats.back')}>
          <ChevronLeft size={20} strokeWidth={1.5} className="icon-directional" aria-hidden="true" />
        </Link>
        {chat.data && (
          <span className="avatar avatar--sm" data-tint={id % 6} aria-hidden="true">
            {chat.data.customer_name?.trim() ? initial(name) : <Phone size={14} strokeWidth={1.5} />}
          </span>
        )}
        <div className="transcript__who">
          <h2 id="transcript-title" className="transcript__name">
            {chat.data ? <bdi>{name}</bdi> : missing ? t('chats.notFound') : t('loading')}
          </h2>
          {chat.data && (
            <p className="transcript__sub">
              <bdi dir="ltr" className="num">
                {formatNumber(chat.data.external_user_id)}
              </bdi>
              <span aria-hidden="true"> · </span>
              {channelLabel(chat.data.channel, t)}
              <span aria-hidden="true"> · </span>
              {t('chats.count', { n: fmt.number(list.length || chat.data.message_count) })}
            </p>
          )}
        </div>
        <div className="transcript__actions" role="toolbar" aria-label={t('chats.actions')}>
          {/* Later: pause or resume the AI, take over, hand over, quote request. Read-only in v1. */}
        </div>
      </header>

      {!missing && (
        <div className="transcript__canvas" ref={ref} onScroll={onScroll}>
          <ol className="bubbles" aria-live="polite" aria-relevant="additions">
            {messages.isPending
              ? Array.from({ length: 5 }, (_, index) => (
                  <li key={index} className={`bubble-row bubble-row--${index % 2 ? 'end' : 'start'}`} aria-hidden="true">
                    <span className="bubble skeleton" style={{ inlineSize: `${30 + ((index * 17) % 35)}%`, blockSize: 44 }} />
                  </li>
                ))
              : list.length === 0
                ? <li className="empty__text transcript__none">{t('chats.noMessages')}</li>
                : list.map((message, index) => {
                    const previous = list[index - 1]
                    const day = fmt.dayLabel(message.created_at)
                    const newDay = !previous || fmt.dayLabel(previous.created_at) !== day
                    return (
                      <Fragment key={message.id}>
                        {newDay && (
                          <li className="day-separator">
                            <span>{day}</span>
                          </li>
                        )}
                        <ChatBubble message={message} first={newDay || previous?.author !== message.author} />
                      </Fragment>
                    )
                  })}
          </ol>
        </div>
      )}

      {!missing && (
        <footer className="transcript__footer">
          <Lock {...ICON} />
          {t('chats.readOnly')}
        </footer>
      )}
    </section>
  )
}

function ChatBubble({ message, first }: { message: TranscriptMessage; first: boolean }) {
  const { t } = useI18n()
  const label = t(message.author === 'customer' ? 'author.customer' : message.author === 'ai' ? 'author.ai' : 'author.staff')
  return (
    <MessageBubble
      message={message}
      label={label}
      tone={message.author}
      side={message.author === 'customer' ? 'start' : 'end'}
      first={first}
      showDelivery={message.author !== 'customer'}
    />
  )
}
