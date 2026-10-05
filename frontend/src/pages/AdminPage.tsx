import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import * as api from '../api'
import { useAuth } from '../authContext'
import { ErrorMessage } from '../components/ErrorMessage'
import { Pagination } from '../components/Pagination'
import type { AuditEntry, Page, Role, User } from '../types'

const ROLES: Role[] = ['admin', 'researcher', 'viewer']

export function AdminPage() {
  return (
    <>
      <UsersPanel />
      <AuditPanel />
    </>
  )
}

function UsersPanel() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('researcher')

  const load = useCallback(() => {
    api.listUsers().then(setUsers).catch((err) => setError(api.messageOf(err)))
  }, [])
  useEffect(load, [load])

  async function change(id: number, changes: { role?: Role; is_active?: boolean }) {
    setError(null)
    try {
      const updated = await api.updateUser(id, changes)
      setUsers((list) => list.map((u) => (u.id === id ? updated : u)))
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await api.createUser(email, password, role)
      setEmail('')
      setPassword('')
      load()
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  return (
    <section className="card">
      <h2>Users</h2>
      <ErrorMessage error={error} />
      <table>
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => {
            const isMe = u.id === me?.id // the API refuses self-changes (400); don't offer them
            return (
              <tr key={u.id}>
                <td>
                  {u.email} {isMe && <span className="muted small">(you)</span>}
                </td>
                <td>
                  <select
                    value={u.role}
                    disabled={isMe}
                    onChange={(e) => change(u.id, { role: e.target.value as Role })}
                    aria-label={`Role for ${u.email}`}
                  >
                    {ROLES.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <button
                    type="button"
                    className={u.is_active ? 'secondary' : ''}
                    disabled={isMe}
                    onClick={() => change(u.id, { is_active: !u.is_active })}
                  >
                    {u.is_active ? 'Active — deactivate' : 'Inactive — activate'}
                  </button>
                </td>
                <td className="small">{new Date(u.created_at).toLocaleDateString()}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <form className="inline-form" onSubmit={create}>
        <h3>Add user</h3>
        <input type="email" placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input
          type="password"
          placeholder="password (8+ characters)"
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="New user role">
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <button type="submit">Create</button>
      </form>
    </section>
  )
}

function AuditPanel() {
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<Page<AuditEntry> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listAudit(page).then(setResult).catch((err) => setError(api.messageOf(err)))
  }, [page])

  return (
    <section className="card">
      <h2>Audit log</h2>
      <ErrorMessage error={error} />
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>User</th>
            <th>Action</th>
            <th>Entity</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {result?.items.map((entry) => (
            <tr key={entry.id}>
              <td className="small">{new Date(entry.created_at).toLocaleString()}</td>
              <td>{entry.user_email ?? '—'}</td>
              <td>
                <span className="badge">{entry.action}</span>
              </td>
              <td>
                {entry.entity_type} #{entry.entity_id ?? '—'}
              </td>
              <td className="mono small">{entry.details ? JSON.stringify(entry.details) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result && (
        <Pagination page={result.page} pageSize={result.page_size} total={result.total} onChange={setPage} />
      )}
    </section>
  )
}
