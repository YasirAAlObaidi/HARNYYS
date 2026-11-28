import { useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useChat, useChats, useTranscript } from '../api/queries'
import type { ChatSummary, TranscriptMessage } from '../api/types'
import { BackIcon, SearchIcon } from '../components/icons'
import { MessageBubble } from '../components/MessageBubble'
import { useI18n } from '../i18n/context'
import type { MessageKey } from '../i18n/messages'
import { displayName, formatNumber, initial } from '../lib/people'
import { useDebounced } from '../lib/useDebounced'
import { useStickToBottom } from '../lib/useStickToBottom'

/**
 * Page 1: every customer chat the AI is handling, read-only (v1). The list sits at the inline start, the open
 * chat beside it; on a phone one shows at a time. Status chips and actions (pause the AI, take over, hand over,
 * quote request) are not built yet: their places are marked `chat-item__chips` and `transcript__actions`.
 */
export function ChatsPage() {
  const params = useParams()
  const id = params.id && /^\d+$/.test(params.id) ? Number(params.id) : null

  return (
    <div className={`chats ${id === null ? 'chats--list' : 'chats--open'}`}>
      <ChatList selected={id} />
      {id === null ? <EmptyPane /> : <Transcript key={id} id={id} />}
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

  return (
    <section className="chat-list" aria-labelledby="chats-title">
      <div className="chat-list__head">
        <h1 id="chats-title" className="page-title">
          {t('chats.title')}
        </h1>
        <label className="search">
          <SearchIcon className="search__icon" />
          <span className="visually-hidden">{t('chats.search')}</span>
          <input
            type="search"
            className="search__input"
            placeholder={t('chats.search')}
            dir="auto"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>
      {chats.isPending ? (
        <p className="muted pad">{t('loading')}</p>
      ) : chats.isError && !chats.data ? (
        <p className="form-error pad" role="alert">
          {chats.error instanceof ApiError && chats.error.status === 0 ? t('error.network') : t('error.generic')}
        </p>
      ) : chats.data.length === 0 ? (
        <p className="muted pad">{query.trim() ? t('chats.noResults', { q: query.trim() }) : t('chats.empty')}</p>
      ) : (
        <ul className="chat-list__items">
          {chats.data.map((chat) => (
            <li key={chat.id}>
              <ChatItem chat={chat} selected={chat.id === selected} when={fmt.when} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ChatItem({ chat, selected, when }: { chat: ChatSummary; selected: boolean; when: (iso: string) => string }) {
  const { t } = useI18n()
  const name = displayName(chat)
  const last = chat.last_message_at ?? chat.last_inbound_at ?? chat.created_at
  const prefix =
    chat.last_message_author === 'ai' ? t('preview.ai') : chat.last_message_author === 'staff' ? t('preview.staff') : ''
  return (
    <NavLink
      to={`/chats/${chat.id}`}
      className={`chat-item${selected ? ' chat-item--selected' : ''}`}
      aria-current={selected ? 'page' : undefined}
    >
      <span className="avatar" aria-hidden="true">
        {initial(name)}
      </span>
      <span className="chat-item__body">
        <span className="chat-item__top">
          <bdi className="chat-item__name">{name}</bdi>
          <time className="chat-item__time" dateTime={last}>
            {when(last)}
          </time>
        </span>
        <span className="chat-item__preview">
          {prefix}
          <bdi>{chat.last_message_text ?? ''}</bdi>
        </span>
        <span className="chat-item__chips">
          <span className="chip">{channelLabel(chat.channel, t)}</span>
          {/* Later: status chips such as "AI paused" or "Needs staff" go here. */}
        </span>
      </span>
    </NavLink>
  )
}

function EmptyPane() {
  const { t } = useI18n()
  return (
    <section className="transcript transcript--empty">
      <p className="muted">{t('chats.select')}</p>
    </section>
  )
}

function Transcript({ id }: { id: number }) {
  const { t, fmt } = useI18n()
  const chat = useChat(id)
  const messages = useTranscript(id)
  const list = messages.data ?? []
  const { ref, onScroll } = useStickToBottom<HTMLOListElement>(list.length, id)
  const missing = chat.error instanceof ApiError && chat.error.status === 404

  return (
    <section className="transcript" aria-labelledby="transcript-title">
      <header className="transcript__header">
        <Link to="/chats" className="transcript__back">
          <BackIcon />
          <span>{t('chats.back')}</span>
        </Link>
        <div className="transcript__who">
          <h2 id="transcript-title" className="transcript__name">
            {chat.data ? <bdi>{displayName(chat.data)}</bdi> : missing ? t('chats.notFound') : t('loading')}
          </h2>
          {chat.data && (
            <p className="transcript__sub">
              <bdi dir="ltr">{formatNumber(chat.data.external_user_id)}</bdi>
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
      {!missing && <p className="notice">{t('chats.readOnly')}</p>}
      {!missing && (
        <ol className="bubbles" ref={ref} onScroll={onScroll} aria-live="polite" aria-relevant="additions">
          {messages.isPending ? (
            <li className="muted pad">{t('loading')}</li>
          ) : list.length === 0 ? (
            <li className="muted pad">{t('chats.noMessages')}</li>
          ) : (
            list.map((message) => <ChatBubble key={message.id} message={message} />)
          )}
        </ol>
      )}
    </section>
  )
}

function ChatBubble({ message }: { message: TranscriptMessage }) {
  const { t } = useI18n()
  const label = t(message.author === 'customer' ? 'author.customer' : message.author === 'ai' ? 'author.ai' : 'author.staff')
  return (
    <MessageBubble
      message={message}
      label={label}
      tone={message.author}
      side={message.author === 'customer' ? 'start' : 'end'}
      showDelivery={message.author !== 'customer'}
    />
  )
}
