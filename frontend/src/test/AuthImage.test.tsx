import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import * as api from '../api'
import { AuthImage } from '../components/AuthImage'

beforeEach(() => {
  api.setToken('secret-token')
  URL.createObjectURL = vi.fn(() => 'blob:fake-url')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.unstubAllGlobals())

it('fetches the image WITH the token and shows it through a blob URL', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('jpeg bytes'))
  vi.stubGlobal('fetch', fetchMock)

  const { unmount } = render(<AuthImage path="/images/3/thumbnail" alt="leaf" />)

  const img = await screen.findByRole('img', { name: 'leaf' })
  expect(img).toHaveAttribute('src', 'blob:fake-url')
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/images/3/thumbnail')
  expect(init.headers.Authorization).toBe('Bearer secret-token')

  unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake-url') // no memory leak
})

it('shows a placeholder when the image cannot be loaded', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 404 })))
  render(<AuthImage path="/images/99/thumbnail" alt="missing" />)
  expect(await screen.findByText('Image unavailable')).toBeInTheDocument()
})
