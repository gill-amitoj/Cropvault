// What the UI SHOWS each role. This is convenience only: the backend enforces every rule
// and returns 403 if a hidden action is attempted anyway (trap #8).
import type { ImageRecord, User } from './types'

export const isAdmin = (user: User | null) => user?.role === 'admin'

export const canUpload = (user: User | null) =>
  user?.role === 'admin' || user?.role === 'researcher'

/** Edit metadata / delete: admins anything, researchers only their own images. */
export const canEditImage = (user: User | null, image: ImageRecord) =>
  user?.role === 'admin' || (user?.role === 'researcher' && user.id === image.uploaded_by)
