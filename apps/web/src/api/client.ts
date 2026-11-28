// One small fetch wrapper for the yyai API. Same origin only: Caddy serves the app and /api together,
// and the session is an HttpOnly cookie the browser sends by itself (the app never sees it).

export class ApiError extends Error {
  readonly status: number
  readonly retryAfterS: number | null

  /** status 0 means the server could not be reached at all. */
  constructor(status: number, message: string, retryAfterS: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfterS = retryAfterS
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  signal?: AbortSignal
}

export async function api<T>(path: string, { method = 'GET', body, signal }: RequestOptions = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'network')
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const data = (await response.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // Not JSON (for example Caddy's own error page). Keep the status text.
    }
    const retryAfter = Number(response.headers.get('Retry-After'))
    throw new ApiError(response.status, detail, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null)
  }
  return (await response.json()) as T
}

export function isUnauthorised(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}
