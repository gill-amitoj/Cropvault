import { describe, expect, it } from 'vitest'

import { canEditImage, canUpload, isAdmin } from '../permissions'
import type { ImageRecord, Role, User } from '../types'

const user = (id: number, role: Role): User => ({
  id,
  role,
  email: `${role}@example.com`,
  is_active: true,
  created_at: '2026-10-01T00:00:00Z',
})
const image = { id: 1, uploaded_by: 7 } as ImageRecord

describe('what the UI shows each role (the backend enforces the real rules)', () => {
  it('upload: admin and researcher, not viewer', () => {
    expect(canUpload(user(1, 'admin'))).toBe(true)
    expect(canUpload(user(1, 'researcher'))).toBe(true)
    expect(canUpload(user(1, 'viewer'))).toBe(false)
    expect(canUpload(null)).toBe(false)
  })

  it('edit/delete image: admin any, researcher only own, viewer never', () => {
    expect(canEditImage(user(1, 'admin'), image)).toBe(true)
    expect(canEditImage(user(7, 'researcher'), image)).toBe(true)
    expect(canEditImage(user(8, 'researcher'), image)).toBe(false)
    expect(canEditImage(user(7, 'viewer'), image)).toBe(false)
  })

  it('admin page: admin only', () => {
    expect(isAdmin(user(1, 'admin'))).toBe(true)
    expect(isAdmin(user(1, 'researcher'))).toBe(false)
  })
})
