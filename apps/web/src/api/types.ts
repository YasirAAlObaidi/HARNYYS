// The shapes the yyai API returns. Kept in step with apps/server/src/yyai/entry/api/app.py,
// core/types.py (ConversationSummary, TranscriptMessage) and services/insights.py (the snapshot).

export type Role = 'admin' | 'sales' | 'viewer'
export type Permission = 'chats' | 'insights' | 'assistant' | 'approve' | 'admin'

export interface StaffUser {
  id: number
  username: string
  display_name: string | null
  role: Role
  permissions: Permission[]
}

export type Author = 'customer' | 'ai' | 'staff'

export interface ChatSummary {
  id: number
  channel: string
  external_user_id: string
  customer_name: string | null
  last_inbound_at: string | null
  created_at: string
  last_message_at: string | null
  last_message_text: string | null
  last_message_author: Author | null
  message_count: number
}

export interface TranscriptMessage {
  id: number
  direction: 'in' | 'out'
  author: Author
  text: string
  media: string[]
  created_at: string
  delivery: string | null
}

export interface AssistantHistory {
  messages: TranscriptMessage[]
  pending: boolean
}

// --- insights --------------------------------------------------------------------------------------------------

/** A metric with no data source yet. The page shows "Not tracked yet", never a number. */
export interface NotTracked {
  status: 'not_tracked'
  needs: string
}

/** "live": counted from stored rows. "estimate": from a rule of thumb, labelled as an estimate. */
export type Metric<T> = ({ status: 'live' | 'estimate' } & T) | NotTracked

export interface DailyValue {
  date: string
  value: number
}

export interface DailyChats {
  date: string
  chats: number
  messages: number
}

export interface TopProduct {
  code: string
  name_en: string | null
  name_ar: string | null
  chats: number
  asks: number
}

export interface Miss {
  query: string
  count: number
  kind: 'none' | 'weak'
}

export interface Heatmap {
  /** 7 rows (Monday first) of 24 hourly counts, in the client's timezone. */
  cells: number[][]
  max: number
}

export interface PeriodData {
  first_day: string
  last_day: string
  leads: {
    new_contacts: Metric<{ value: number }>
    active_contacts: Metric<{ value: number }>
    new_vs_returning: Metric<{ new: number; returning: number }>
    new_contacts_daily: Metric<{ series: DailyValue[] }>
    quote_requests: Metric<{ value: number }>
    quotes_sent: Metric<{ value: number }>
    lost_leads: Metric<{ value: number }>
    lost_at_step: Metric<{ steps: { step: string; count: number }[] }>
  }
  demand: {
    top_products: Metric<{ lookups: number; items: TopProduct[] }>
    price_vs_stock: Metric<{ price: number; stock: number; both: number; messages: number }>
    not_found: Metric<{ searches: number; no_match: number; weak_match: number; top: Miss[] }>
    languages: Metric<{ arabic: number; english: number; other: number; messages: number }>
    voice_notes: Metric<{ count: number; chats: number; messages: number }>
  }
  busy: {
    heatmap: Metric<Heatmap>
    chats_daily: Metric<{ series: DailyChats[] }>
    after_hours: Metric<{ after_hours: number; messages: number; hours_confirmed: boolean }>
    lost_leads_heatmap: Metric<Heatmap>
  }
}

export type PeriodKey = 'today' | '7d' | '30d' | 'month'
export const PERIODS: PeriodKey[] = ['today', '7d', '30d', 'month']

export interface InsightSnapshot {
  version: number
  id: number
  computed_at: string
  next_at: string
  timezone: string
  working_hours: ({ confirmed: boolean } & Record<string, string | boolean>) | null
  periods: Record<PeriodKey, PeriodData>
  not_tracked: Record<string, string>
}
