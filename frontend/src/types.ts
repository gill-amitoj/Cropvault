// Shapes returned by the API (see backend response models).

export type Role = 'admin' | 'researcher' | 'viewer'

export interface User {
  id: number
  email: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface Experiment {
  id: number
  code: string
  title: string
  description: string | null
  created_by: number | null
  created_at: string
}

export interface ImageRecord {
  id: number
  experiment_id: number | null
  experiment_code: string | null
  crop_species: string | null
  capture_date: string | null
  station_id: string | null
  original_filename: string
  content_type: string
  size_bytes: number
  width: number
  height: number
  sha256: string
  exif: Record<string, unknown> | null
  tags: string[]
  uploaded_by: number
  parent_image_id: number | null
  derivation: 'crop' | 'mask' | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AuditEntry {
  id: number
  user_id: number | null
  user_email: string | null
  action: string
  entity_type: string
  entity_id: number | null
  details: Record<string, unknown> | null
  created_at: string
}
