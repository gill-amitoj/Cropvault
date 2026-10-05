import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'

import { AuthContext } from '../authContext'
import type { AuthState } from '../authContext'
import { LoginPage } from '../pages/LoginPage'

function renderLogin(login: AuthState['login']) {
  render(
    <AuthContext.Provider value={{ user: null, loading: false, login, logout: vi.fn() }}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<p>Gallery page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

it('logs in with the typed credentials and goes to the gallery', async () => {
  const login = vi.fn().mockResolvedValue(undefined)
  renderLogin(login)

  await userEvent.type(screen.getByLabelText('Email'), 'admin@example.com')
  await userEvent.type(screen.getByLabelText('Password'), 'secret-pass')
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }))

  expect(login).toHaveBeenCalledWith('admin@example.com', 'secret-pass')
  expect(await screen.findByText('Gallery page')).toBeInTheDocument()
})

it('shows the API error when login fails', async () => {
  renderLogin(vi.fn().mockRejectedValue(new Error('Invalid email or password')))

  await userEvent.type(screen.getByLabelText('Email'), 'admin@example.com')
  await userEvent.type(screen.getByLabelText('Password'), 'wrong')
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
})
