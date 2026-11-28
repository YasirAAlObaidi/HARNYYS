import { MutationCache, QueryCache, QueryClient, keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, isUnauthorised } from './client'
import type { AssistantHistory, ChatSummary, InsightSnapshot, StaffUser, TranscriptMessage } from './types'

// How often each page asks for news. Polling stops while the browser tab is hidden.
export const CHAT_LIST_POLL_MS = 5_000
export const TRANSCRIPT_POLL_MS = 3_000
export const ASSISTANT_WAITING_POLL_MS = 1_500
export const ASSISTANT_IDLE_POLL_MS = 15_000
const INSIGHTS_GRACE_MS = 60_000 // the worker needs a moment after the hour to compute the snapshot
const INSIGHTS_RETRY_MS = 60_000

const ME = ['me'] as const

/** One client for the app. Any 401 means the session ended: drop the user, so the login page shows. */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isUnauthorised(error) && query.queryKey[0] !== 'me') client.setQueryData(ME, null)
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        if (isUnauthorised(error)) client.setQueryData(ME, null)
      },
    }),
    defaultOptions: {
      queries: {
        retry: (failures, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
        refetchOnWindowFocus: true,
      },
    },
  })
  return client
}

// --- session --------------------------------------------------------------------------------------------------

export function useMe() {
  return useQuery({
    queryKey: ME,
    queryFn: async ({ signal }) => {
      try {
        return (await api<{ user: StaffUser }>('/api/auth/me', { signal })).user
      } catch (error) {
        if (isUnauthorised(error)) return null
        throw error
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export interface LoginInput {
  username: string
  password: string
  code: string
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: LoginInput) => api<{ user: StaffUser }>('/api/auth/login', { method: 'POST', body: input }),
    onSuccess: ({ user }) => client.setQueryData(ME, user),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ logged_out: boolean }>('/api/auth/logout', { method: 'POST' }),
    onSettled: () => {
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
      client.setQueryData(ME, null)
    },
  })
}

// --- page 1: chats ----------------------------------------------------------------------------------------------

export function useChats(search: string) {
  const q = search.trim()
  return useQuery({
    queryKey: ['chats', q],
    queryFn: ({ signal }) =>
      api<ChatSummary[]>(`/api/conversations?limit=200${q ? `&q=${encodeURIComponent(q)}` : ''}`, { signal }),
    refetchInterval: CHAT_LIST_POLL_MS,
    placeholderData: keepPreviousData,
  })
}

export function useChat(id: number | null) {
  return useQuery({
    queryKey: ['chat', id],
    queryFn: ({ signal }) => api<ChatSummary>(`/api/conversations/${id}`, { signal }),
    enabled: id !== null,
  })
}

export function useTranscript(id: number | null) {
  return useQuery({
    queryKey: ['transcript', id],
    queryFn: ({ signal }) => api<TranscriptMessage[]>(`/api/conversations/${id}/messages?limit=500`, { signal }),
    enabled: id !== null,
    refetchInterval: TRANSCRIPT_POLL_MS,
  })
}

// --- page 2: the assistant ----------------------------------------------------------------------------------------

export function useAssistant() {
  return useQuery({
    queryKey: ['assistant'],
    queryFn: ({ signal }) => api<AssistantHistory>('/api/assistant/messages', { signal }),
    refetchInterval: (query) => (query.state.data?.pending ? ASSISTANT_WAITING_POLL_MS : ASSISTANT_IDLE_POLL_MS),
  })
}

export function useSendToAssistant() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { text: string; client_id: string }) =>
      api<{ queued: boolean }>('/api/assistant/messages', { method: 'POST', body: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['assistant'] }),
  })
}

// --- page 3: insights ---------------------------------------------------------------------------------------------

/**
 * When to ask for the snapshot again: just after the worker's next run (next_at plus a minute), or every
 * minute while a snapshot is missing or late.
 */
export function insightsRefetchMs(snapshot: InsightSnapshot | null | undefined, now: number = Date.now()): number {
  if (!snapshot) return INSIGHTS_RETRY_MS
  const wait = Date.parse(snapshot.next_at) + INSIGHTS_GRACE_MS - now
  return wait > 0 ? wait : INSIGHTS_RETRY_MS
}

export function useInsights() {
  return useQuery({
    queryKey: ['insights'],
    queryFn: async ({ signal }) => (await api<{ snapshot: InsightSnapshot | null }>('/api/insights', { signal })).snapshot,
    refetchInterval: (query) => insightsRefetchMs(query.state.data),
  })
}
