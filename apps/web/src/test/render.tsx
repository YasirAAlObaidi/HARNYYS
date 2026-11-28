import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'

import { createQueryClient } from '../api/queries'
import type { StaffUser } from '../api/types'
import { AppProviders } from '../AppProviders'
import { routes } from '../routes'

export const SALES_USER: StaffUser = {
  id: 1,
  username: 'sara',
  display_name: 'Sara',
  role: 'sales',
  permissions: ['approve', 'assistant', 'chats', 'insights'],
}

export const VIEWER: StaffUser = { id: 2, username: 'vera', display_name: null, role: 'viewer', permissions: ['chats', 'insights'] }

type Handler = (body: unknown, url: URL) => unknown
export interface Call {
  method: string
  path: string
  body: unknown
}

/**
 * Replace fetch with a tiny fake API. Keys are "METHOD /path" (no query string). A handler returns a body
 * (sent as 200 JSON) or a Response. Unknown routes answer 404. Returns the list of calls made.
 */
export function fakeApi(routesByKey: Record<string, Handler | unknown>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'https://kahraman.test')
      const method = (init?.method ?? 'GET').toUpperCase()
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname + url.search, body })
      const key = `${method} ${url.pathname}`
      if (!(key in routesByKey)) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
      const route = routesByKey[key]
      const result = typeof route === 'function' ? (route as Handler)(body, url) : route
      if (result instanceof Response) return result
      return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

export function renderAt(path: string) {
  const client = createQueryClient() // the app's own client, with its "401 means logged out" handling
  client.setDefaultOptions({ queries: { retry: false } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  return { ...view, router, client }
}
