const BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ApiConfig {
  getToken: () => string | null
  onUnauthorized: () => void
}

// The AuthProvider plugs itself in here, so this file never imports from features/auth.
let config: ApiConfig = {
  getToken: () => null,
  onUnauthorized: () => {},
}

export function configureApi(next: ApiConfig) {
  config = next
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    // FastAPI: `detail` is a string for HTTPException, an array for 422s
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg: string }) => d.msg).join(', ')
    }
  } catch {
    // body wasn't JSON
  }
  return `Request failed (${res.status})`
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')

  const token = config.getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })

  if (!res.ok) {
    // A 401 while we had a token means it expired or was rejected: drop the session.
    if (res.status === 401 && token) config.onUnauthorized()
    throw new ApiError(res.status, await readError(res))
  }

  return res.json() as Promise<T>
}
