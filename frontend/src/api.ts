// The only module that talks to the backend. Every request goes to /api on the same origin
// (the Vite dev server forwards it to FastAPI) and carries the JWT if we have one.
import type { AuditEntry, Experiment, ImageRecord, Page, Role, User } from './types'

const TOKEN_KEY = 'cropvault_token'

// Token lives in memory, mirrored to localStorage so a page refresh keeps you logged in.
// Trade-off vs an httpOnly cookie: see docs/decisions.md (Stage 2).
let token: string | null = readStoredToken()

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return token
}

export function setToken(value: string | null): void {
  token = value
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Storage blocked (private mode): the in-memory token still works for this tab.
  }
}

// Called when the API rejects our token (expired, user deactivated). Set by the auth provider.
let onUnauthorized: () => void = () => {}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(errorMessage(status, detail))
    this.status = status
    this.detail = detail
  }
}

/** Turn the API's {"detail": ...} into one readable sentence. */
export function errorMessage(status: number, detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI 422: [{loc: ["body", "email"], msg: "..."}]
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = item.loc?.filter((part) => part !== 'body' && part !== 'query').join('.')
        return field ? `${field}: ${item.msg}` : item.msg
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return `Request failed (HTTP ${status})`
}

interface RequestOptions {
  method?: string
  json?: unknown
  form?: FormData
  query?: Record<string, string | number | undefined | null>
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {}
  const sentToken = token
  if (sentToken) headers.Authorization = `Bearer ${sentToken}`

  let body: BodyInit | undefined
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  } else if (options.form) {
    body = options.form // browser sets the multipart boundary itself
  }

  let url = `/api${path}`
  if (options.query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }

  const response = await fetch(url, { method: options.method ?? 'GET', headers, body })
  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = (await response.json()).detail
    } catch {
      // not JSON (e.g. proxy error page)
    }
    // A 401 on a request that carried a token means the session is over. (A 401 from the
    // login form itself is just a wrong password and must not log anyone out.)
    if (response.status === 401 && sentToken) {
      setToken(null)
      onUnauthorized()
    }
    throw new ApiError(response.status, detail)
  }
  return response
}

async function requestJson<T>(path: string, options?: RequestOptions): Promise<T> {
  const response = await send(path, options)
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

/** Images must be fetched with the token: an <img src> can't send an Authorization header. */
export async function fetchBlob(path: string): Promise<Blob> {
  return (await send(path)).blob()
}

// --- auth ---------------------------------------------------------------------------------

export async function login(email: string, password: string): Promise<void> {
  const result = await requestJson<{ access_token: string }>('/auth/login', {
    method: 'POST',
    json: { email, password },
  })
  setToken(result.access_token)
}

export const getMe = () => requestJson<User>('/auth/me')

// --- images -------------------------------------------------------------------------------

export interface ImageFilters {
  species?: string
  experiment?: string
  station?: string
  tags?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export const searchImages = (filters: ImageFilters) =>
  requestJson<Page<ImageRecord>>('/images', { query: { ...filters } })

export const getImage = (id: number) => requestJson<ImageRecord>(`/images/${id}`)

export interface ImageUpdate {
  experiment_code?: string | null
  crop_species?: string | null
  station_id?: string | null
  capture_date?: string | null
  tags?: string[]
}

export const updateImage = (id: number, changes: ImageUpdate) =>
  requestJson<ImageRecord>(`/images/${id}`, { method: 'PATCH', json: changes })

export const deleteImage = (id: number) =>
  requestJson<void>(`/images/${id}`, { method: 'DELETE' })

export const uploadImage = (form: FormData) =>
  requestJson<ImageRecord>('/images', { method: 'POST', form })

export const imageFilePath = (id: number) => `/images/${id}/file`
export const thumbnailPath = (id: number) => `/images/${id}/thumbnail`

// --- experiments, users, audit -----------------------------------------------------------

export const listExperiments = () => requestJson<Experiment[]>('/experiments')

export const listUsers = () => requestJson<User[]>('/users')

export const createUser = (email: string, password: string, role: Role) =>
  requestJson<User>('/users', { method: 'POST', json: { email, password, role } })

export const updateUser = (id: number, changes: { role?: Role; is_active?: boolean }) =>
  requestJson<User>(`/users/${id}`, { method: 'PATCH', json: changes })

export const listAudit = (page: number) =>
  requestJson<Page<AuditEntry>>('/audit', { query: { page } })

/** Readable message for anything thrown (ApiError, network failure, ...). */
export const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err))
