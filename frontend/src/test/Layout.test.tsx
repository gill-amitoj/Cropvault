import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'

import { AuthContext } from '../authContext'
import type { AuthState } from '../authContext'
import { Layout } from '../components/Layout'
import type { Role } from '../types'

function renderAs(role: Role) {
  const auth: AuthState = {
    user: { id: 1, email: `${role}@example.com`, role, is_active: true, created_at: '' },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

it('viewer sees Gallery only', () => {
  renderAs('viewer')
  expect(screen.getByRole('link', { name: 'Gallery' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Upload' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
})

it('researcher sees Upload but not Admin', () => {
  renderAs('researcher')
  expect(screen.getByRole('link', { name: 'Upload' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
})

it('admin sees Upload and Admin', () => {
  renderAs('admin')
  expect(screen.getByRole('link', { name: 'Upload' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
})
