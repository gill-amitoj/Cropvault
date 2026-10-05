import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api'

function mockFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => api.setToken(null))
afterEach(() => vi.unstubAllGlobals())

describe('api requests', () => {
  it('sends the JWT as a bearer header when logged in', async () => {
    api.setToken('abc123')
    const fetchMock = mockFetch(200, { id: 1 })

    await api.getMe()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/me')
    expect(init.headers.Authorization).toBe('Bearer abc123')
  })

  it('stores the token from login in localStorage', async () => {
    mockFetch(200, { access_token: 'new-token' })
    await api.login('a@example.com', 'pw')
    expect(api.getToken()).toBe('new-token')
    expect(localStorage.getItem('cropvault_token')).toBe('new-token')
  })

  it('a 401 on an authenticated request clears the token and calls the handler', async () => {
    const handler = vi.fn()
    api.setUnauthorizedHandler(handler)
    api.setToken('expired')
    mockFetch(401, { detail: 'Invalid or expired token' })

    await expect(api.getMe()).rejects.toThrow('Invalid or expired token')
    expect(api.getToken()).toBeNull()
    expect(handler).toHaveBeenCalledOnce()
  })

  it('a 401 from the login form (wrong password) does not trigger logout', async () => {
    const handler = vi.fn()
    api.setUnauthorizedHandler(handler)
    mockFetch(401, { detail: 'Invalid email or password' })

    await expect(api.login('a@example.com', 'wrong')).rejects.toThrow('Invalid email or password')
    expect(handler).not.toHaveBeenCalled()
  })

  it('drops empty filters from the query string', async () => {
    api.setToken('t')
    const fetchMock = mockFetch(200, { items: [], total: 0, page: 1, page_size: 24 })
    await api.searchImages({ species: 'wheat', station: '', tags: 'drought,leaf', page: 2 })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/images?species=wheat&tags=drought%2Cleaf&page=2')
  })

  it('a 409 duplicate keeps the existing image id on the error', async () => {
    api.setToken('t')
    mockFetch(409, { detail: { message: 'Duplicate image', image_id: 12 } })
    const error = await api.uploadImage(new FormData()).catch((err) => err)
    expect(error).toBeInstanceOf(api.ApiError)
    expect(error.status).toBe(409)
    expect(error.message).toBe('Duplicate image')
    expect(error.detail.image_id).toBe(12)
  })
})

describe('errorMessage', () => {
  it('uses a string detail as-is', () => {
    expect(api.errorMessage(403, 'Not allowed for your role')).toBe('Not allowed for your role')
  })

  it('formats FastAPI 422 validation lists', () => {
    const detail = [
      { loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
      { loc: ['query', 'page'], msg: 'Input should be greater than or equal to 1' },
    ]
    expect(api.errorMessage(422, detail)).toBe(
      'password: String should have at least 8 characters; page: Input should be greater than or equal to 1',
    )
  })

  it('falls back to the status code', () => {
    expect(api.errorMessage(502, null)).toBe('Request failed (HTTP 502)')
  })
})
