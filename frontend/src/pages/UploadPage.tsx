import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import * as api from '../api'
import { ErrorMessage } from '../components/ErrorMessage'
import type { Experiment } from '../types'

const MAX_BYTES = 20 * 1024 * 1024 // same limit as the API (which enforces it; this is just early feedback)

export function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [experiment, setExperiment] = useState('')
  const [species, setSpecies] = useState('')
  const [station, setStation] = useState('')
  const [date, setDate] = useState('')
  const [tags, setTags] = useState('')
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [error, setError] = useState<string | null>(null)
  const [duplicateOf, setDuplicateOf] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.listExperiments().then(setExperiments).catch(() => setExperiments([]))
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setDuplicateOf(null)
    if (!file) return setError('Choose a file first.')
    if (file.size > MAX_BYTES) return setError('File is larger than 20 MB.')

    const form = new FormData()
    form.append('file', file)
    if (experiment) form.append('experiment_code', experiment)
    if (species) form.append('crop_species', species)
    if (station) form.append('station_id', station)
    if (date) form.append('capture_date', date)
    if (tags) form.append('tags', tags)

    setBusy(true)
    try {
      const image = await api.uploadImage(form)
      navigate(`/images/${image.id}`)
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 409) {
        setDuplicateOf((err.detail as { image_id: number }).image_id)
      } else {
        setError(api.messageOf(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card stack narrow" onSubmit={handleSubmit}>
      <h2>Upload an image</h2>
      <p className="muted small">JPEG, PNG or TIFF, up to 20 MB. The original is stored unchanged.</p>
      <label>
        File
        <input
          type="file"
          accept=".jpg,.jpeg,.png,.tif,.tiff,image/jpeg,image/png,image/tiff"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
        />
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
        Species
        <input value={species} onChange={(e) => setSpecies(e.target.value)} placeholder="e.g. Wheat" />
      </label>
      <label>
        Station
        <input value={station} onChange={(e) => setStation(e.target.value)} placeholder="e.g. ST01" />
      </label>
      <label>
        Capture date <span className="muted small">(blank = read from EXIF)</span>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>
        Tags (comma-separated)
        <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="drought, leaf" />
      </label>
      <ErrorMessage error={error} />
      {duplicateOf !== null && (
        <p className="error" role="alert">
          This exact file is already stored as <Link to={`/images/${duplicateOf}`}>image #{duplicateOf}</Link>.
        </p>
      )}
      <button type="submit" disabled={busy}>
        {busy ? 'Uploading…' : 'Upload'}
      </button>
    </form>
  )
}
