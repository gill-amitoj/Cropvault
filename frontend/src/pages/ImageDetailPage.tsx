import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import * as api from '../api'
import { useAuth } from '../authContext'
import { AuthImage } from '../components/AuthImage'
import { ErrorMessage } from '../components/ErrorMessage'
import { canEditImage } from '../permissions'
import type { Experiment, ImageRecord } from '../types'

// Chrome and Firefox can't display TIFF, so for TIFFs we show the JPEG thumbnail instead.
const BROWSER_CAN_SHOW = new Set(['image/jpeg', 'image/png'])

const formatBytes = (n: number) =>
  n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`

export function ImageDetailPage() {
  const id = Number(useParams().id)
  // key={id}: moving to another image (e.g. parent link) starts with fresh state.
  return <ImageDetail key={id} id={id} />
}

function ImageDetail({ id }: { id: number }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [image, setImage] = useState<ImageRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    api.getImage(id).then(setImage).catch((err) => setError(api.messageOf(err)))
  }, [id])

  if (error && !image) return <ErrorMessage error={error} />
  if (!image) return <p className="muted">Loading…</p>

  const showOriginal = BROWSER_CAN_SHOW.has(image.content_type)
  const mayEdit = canEditImage(user, image)

  async function download() {
    if (!image) return
    try {
      const blob = await api.fetchBlob(api.imageFilePath(image.id))
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = image.original_filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  async function remove() {
    if (!image || !window.confirm(`Delete ${image.original_filename}? This cannot be undone.`)) return
    try {
      await api.deleteImage(image.id)
      navigate('/')
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  return (
    <div className="detail">
      <div className="detail-image">
        <AuthImage
          path={showOriginal ? api.imageFilePath(image.id) : api.thumbnailPath(image.id)}
          alt={image.original_filename}
          className="full"
        />
        {!showOriginal && (
          <p className="muted small">
            TIFF preview (browsers can't display TIFF). Download the original for full resolution.
          </p>
        )}
      </div>

      <div className="detail-info">
        <p>
          <Link to="/">← Back to gallery</Link>
        </p>
        <h2>{image.original_filename}</h2>
        {image.derivation && image.parent_image_id && (
          <p>
            <span className="badge">{image.derivation}</span> derived from{' '}
            <Link to={`/images/${image.parent_image_id}`}>image #{image.parent_image_id}</Link>
          </p>
        )}
        <ErrorMessage error={error} />

        <div className="actions">
          <button type="button" onClick={download}>
            Download original
          </button>
          {mayEdit && !editing && (
            <button type="button" className="secondary" onClick={() => setEditing(true)}>
              Edit metadata
            </button>
          )}
          {mayEdit && (
            <button type="button" className="danger" onClick={remove}>
              Delete
            </button>
          )}
        </div>

        {editing ? (
          <EditForm
            image={image}
            onSaved={(updated) => {
              setImage(updated)
              setEditing(false)
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <dl className="meta">
            <dt>Species</dt>
            <dd>{image.crop_species ?? '—'}</dd>
            <dt>Experiment</dt>
            <dd>{image.experiment_code ?? '—'}</dd>
            <dt>Station</dt>
            <dd>{image.station_id ?? '—'}</dd>
            <dt>Capture date</dt>
            <dd>{image.capture_date ?? '—'}</dd>
            <dt>Tags</dt>
            <dd>{image.tags.length ? image.tags.join(', ') : '—'}</dd>
            <dt>Format</dt>
            <dd>
              {image.content_type} · {image.width}×{image.height} · {formatBytes(image.size_bytes)}
            </dd>
            <dt>SHA-256</dt>
            <dd className="mono small">{image.sha256}</dd>
            <dt>Uploaded</dt>
            <dd>
              {new Date(image.created_at).toLocaleString()} by user #{image.uploaded_by}
            </dd>
          </dl>
        )}

        {image.exif && Object.keys(image.exif).length > 0 && (
          <>
            <h3>EXIF</h3>
            <dl className="meta">
              {Object.entries(image.exif).map(([key, value]) => (
                <div key={key} className="meta-row">
                  <dt>{key}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </div>
    </div>
  )
}

function EditForm({
  image,
  onSaved,
  onCancel,
}: {
  image: ImageRecord
  onSaved: (image: ImageRecord) => void
  onCancel: () => void
}) {
  const [species, setSpecies] = useState(image.crop_species ?? '')
  const [experiment, setExperiment] = useState(image.experiment_code ?? '')
  const [station, setStation] = useState(image.station_id ?? '')
  const [date, setDate] = useState(image.capture_date ?? '')
  const [tags, setTags] = useState(image.tags.join(', '))
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listExperiments().then(setExperiments).catch(() => setExperiments([]))
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    try {
      onSaved(
        await api.updateImage(image.id, {
          crop_species: species || null,
          experiment_code: experiment || null,
          station_id: station || null,
          capture_date: date || null,
          tags: tags.split(','),
        }),
      )
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <label>
        Species
        <input value={species} onChange={(e) => setSpecies(e.target.value)} />
      </label>
      <label>
        Experiment
        <select value={experiment} onChange={(e) => setExperiment(e.target.value)}>
          <option value="">None</option>
          {experiments.map((exp) => (
            <option key={exp.id} value={exp.code}>
              {exp.code} — {exp.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Station
        <input value={station} onChange={(e) => setStation(e.target.value)} />
      </label>
      <label>
        Capture date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>
        Tags (comma-separated)
        <input value={tags} onChange={(e) => setTags(e.target.value)} />
      </label>
      <ErrorMessage error={error} />
      <div className="actions">
        <button type="submit">Save</button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
