import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import * as api from '../api'
import { AuthImage } from '../components/AuthImage'
import { ErrorMessage } from '../components/ErrorMessage'
import { Pagination } from '../components/Pagination'
import type { Experiment, ImageRecord, Page } from '../types'

const FILTER_KEYS = ['species', 'experiment', 'station', 'tags', 'date_from', 'date_to'] as const
type FilterKey = (typeof FILTER_KEYS)[number]
type Filters = Record<FilterKey, string>

function filtersFrom(params: URLSearchParams): Filters {
  return Object.fromEntries(FILTER_KEYS.map((key) => [key, params.get(key) ?? ''])) as Filters
}

export function GalleryPage() {
  // Filters live in the URL: refresh, back button and shared links all keep them.
  const [params, setParams] = useSearchParams()
  const query = params.toString()
  const applied = filtersFrom(params)
  const page = Math.max(1, Number(params.get('page')) || 1)

  const [experiments, setExperiments] = useState<Experiment[]>([])
  // Results are tagged with the query they belong to, so a slow old response is ignored.
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let cancelled = false
    const search = new URLSearchParams(query)
    api
      .searchImages({ ...filtersFrom(search), page: Math.max(1, Number(search.get('page')) || 1) })
      .then((result) => !cancelled && setLoaded({ query, result, error: null }))
      .catch((err) => !cancelled && setLoaded({ query, result: null, error: api.messageOf(err) }))
    return () => {
      cancelled = true
    }
  }, [query])

  useEffect(() => {
    api.listExperiments().then(setExperiments).catch(() => setExperiments([]))
  }, [])

  function apply(next: Filters, nextPage = 1) {
    const search = new URLSearchParams()
    for (const key of FILTER_KEYS) if (next[key].trim()) search.set(key, next[key].trim())
    if (nextPage > 1) search.set('page', String(nextPage))
    setParams(search)
  }

  const current = loaded?.query === query ? loaded : null
  const result = current?.result ?? null

  return (
    <>
      {/* key: when the URL changes (back button, Clear), the form shows the new filters */}
      <FilterForm key={query} initial={applied} experiments={experiments} onApply={apply} />

      <ErrorMessage error={current?.error ?? null} />
      {!current && <p className="muted">Loading…</p>}
      {result && result.items.length === 0 && <p className="muted">No images match these filters.</p>}

      <div className="grid">
        {result?.items.map((image) => (
          <Link key={image.id} to={`/images/${image.id}`} className="tile">
            <AuthImage path={api.thumbnailPath(image.id)} alt={image.original_filename} className="thumb" />
            <div className="tile-body">
              <strong>{image.crop_species ?? 'Unknown species'}</strong>
              {image.derivation && <span className="badge">{image.derivation}</span>}
              <div className="muted small">
                {image.capture_date ?? 'no date'} · {image.station_id ?? 'no station'}
              </div>
              <div className="small ellipsis">{image.original_filename}</div>
              <div className="tags">
                {image.tags.map((tag) => (
                  <span key={tag} className="tag">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </Link>
        ))}
      </div>

      {result && result.total > result.page_size && (
        <Pagination
          page={page}
          pageSize={result.page_size}
          total={result.total}
          onChange={(next) => apply(applied, next)}
        />
      )}
    </>
  )
}

type Loaded = { query: string; result: Page<ImageRecord> | null; error: string | null }

function FilterForm({
  initial,
  experiments,
  onApply,
}: {
  initial: Filters
  experiments: Experiment[]
  onApply: (filters: Filters) => void
}) {
  const [draft, setDraft] = useState<Filters>(initial)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onApply(draft)
  }

  const set = (key: FilterKey) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value })

  return (
    <form className="filters" onSubmit={handleSubmit}>
      <label>
        Species
        <input value={draft.species} onChange={set('species')} placeholder="e.g. wheat" />
      </label>
      <label>
        Experiment
        <select value={draft.experiment} onChange={set('experiment')}>
          <option value="">Any</option>
          {experiments.map((exp) => (
            <option key={exp.id} value={exp.code}>
              {exp.code} — {exp.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Station
        <input value={draft.station} onChange={set('station')} placeholder="e.g. ST01" />
      </label>
      <label>
        Tags (all of)
        <input value={draft.tags} onChange={set('tags')} placeholder="drought, leaf" />
      </label>
      <label>
        From
        <input type="date" value={draft.date_from} onChange={set('date_from')} />
      </label>
      <label>
        To
        <input type="date" value={draft.date_to} onChange={set('date_to')} />
      </label>
      <div className="filter-buttons">
        <button type="submit">Search</button>
        <button type="button" className="secondary" onClick={() => onApply(filtersFrom(new URLSearchParams()))}>
          Clear
        </button>
      </div>
    </form>
  )
}
