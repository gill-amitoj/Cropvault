import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import * as api from '../api'
import { AuthContext } from '../authContext'
import { AnnotationCanvas } from '../components/AnnotationCanvas'
import type { Annotation, ImageRecord, Role } from '../types'

const image = { id: 5, width: 1280, height: 960, original_filename: 'leaf.jpg' } as ImageRecord
const annotations: Annotation[] = [
  { id: 1, image_id: 5, label: 'rust pustule', kind: 'bbox', geometry: { x: 0.1, y: 0.2, width: 0.3, height: 0.2 }, created_by: 7, created_at: '', updated_at: '' },
  { id: 2, image_id: 5, label: 'leaf edge', kind: 'polygon', geometry: { points: [[0.1, 0.1], [0.9, 0.1], [0.5, 0.8]] }, created_by: 8, created_at: '', updated_at: '' },
]

beforeEach(() => {
  api.setToken('t')
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith('/annotations')
          ? new Response(JSON.stringify(annotations), { headers: { 'Content-Type': 'application/json' } })
          : new Response('image bytes'),
      ),
    ),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAs(id: number, role: Role) {
  render(
    <AuthContext.Provider
      value={{ user: { id, role, email: `${role}@example.com`, is_active: true, created_at: '' }, loading: false, login: vi.fn(), logout: vi.fn() }}
    >
      <MemoryRouter>
        <AnnotationCanvas image={image} imagePath="/images/5/file" />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

it('draws saved annotations as SVG shapes in 0-1 coordinates', async () => {
  renderAs(1, 'viewer')
  expect(await screen.findByText('Annotations (2)')).toBeInTheDocument()
  const layer = screen.getByTestId('annotation-layer')
  expect(layer).toHaveAttribute('viewBox', '0 0 1 1')
  const rect = layer.querySelector('rect')!
  expect(rect).toHaveAttribute('x', '0.1')
  expect(rect).toHaveAttribute('width', '0.3')
  expect(layer.querySelector('polygon')).toHaveAttribute('points', '0.1,0.1 0.9,0.1 0.5,0.8')
})

it('viewer sees annotations but no drawing tools, crop, rename or delete', async () => {
  renderAs(1, 'viewer')
  await screen.findByText('Annotations (2)')
  expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Crop' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
})

it('researcher gets tools, can crop boxes, but can only rename/delete their own', async () => {
  renderAs(7, 'researcher')
  await screen.findByText('Annotations (2)')
  expect(screen.getByRole('toolbar')).toBeInTheDocument()

  const [own, other] = screen.getAllByRole('listitem')
  expect(within(own).getByRole('button', { name: 'Crop' })).toBeInTheDocument()
  expect(within(own).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  expect(within(other).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  expect(within(other).queryByRole('button', { name: 'Crop' })).not.toBeInTheDocument() // polygon
})

it('admin can rename and delete every annotation', async () => {
  renderAs(1, 'admin')
  await screen.findByText('Annotations (2)')
  expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: 'Rename' })).toHaveLength(2)
})
