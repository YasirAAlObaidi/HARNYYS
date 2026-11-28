import type { ChatSummary } from '../api/types'

/** "+971 50 123 4567" style for a WhatsApp number; anything else as it is. */
export function formatNumber(externalUserId: string): string {
  return /^\d{8,15}$/.test(externalUserId) ? `+${externalUserId}` : externalUserId
}

export function displayName(chat: Pick<ChatSummary, 'customer_name' | 'external_user_id'>): string {
  return chat.customer_name?.trim() || formatNumber(chat.external_user_id)
}

/** First letter for the avatar circle (works for Arabic and English names). */
export function initial(name: string): string {
  const letter = Array.from(name.replace(/^\+/, '').trim())[0]
  return letter ? letter.toLocaleUpperCase() : '?'
}
