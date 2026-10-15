import { useEffect, useRef, useState } from 'react'
import type { FormEvent, PointerEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import * as api from '../api'
import { useAuth } from '../authContext'
import { bboxFromPoints, bboxToPixels, isBigEnoughToCrop, isNear, toFraction, CROP_MIN_PX } from '../geometry'
import type { Point } from '../geometry'
import { canAnnotate, canEditAnnotation } from '../permissions'
import type { Annotation, BBoxGeometry, ImageRecord, PolygonGeometry } from '../types'
import { AuthImage } from './AuthImage'
import { ErrorMessage } from './ErrorMessage'

type Tool = 'view' | 'bbox' | 'polygon'
type Draft = { kind: 'bbox'; geometry: BBoxGeometry } | { kind: 'polygon'; geometry: PolygonGeometry }

interface Props {
  image: ImageRecord
  imagePath: string // what to display: the original, or the thumbnail for TIFFs
}

const pointsAttr = (points: [number, number][]) => points.map(([x, y]) => `${x},${y}`).join(' ')
const labelAnchor = (a: { kind: string; geometry: BBoxGeometry | PolygonGeometry }) =>
  a.kind === 'bbox'
    ? { x: (a.geometry as BBoxGeometry).x, y: (a.geometry as BBoxGeometry).y }
    : { x: (a.geometry as PolygonGeometry).points[0][0], y: (a.geometry as PolygonGeometry).points[0][1] }

/**
 * The image with an SVG layer on top. The SVG uses viewBox "0 0 1 1" and no aspect-ratio
 * locking, so its coordinates ARE the stored 0-1 fractions: a shape drawn here lines up with
 * the image at any display size (trap #9). Drawing tools are only shown to admins/researchers;
 * the backend enforces the same rules (trap #8).
 */
export function AnnotationCanvas({ image, imagePath }: Props) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [tool, setTool] = useState<Tool>('view')
  const [dragStart, setDragStart] = useState<Point | null>(null)
  const [dragNow, setDragNow] = useState<Point | null>(null)
  const [polygon, setPolygon] = useState<Point[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [label, setLabel] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [renaming, setRenaming] = useState<{ id: number; label: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [duplicateOf, setDuplicateOf] = useState<number | null>(null)
  const mayDraw = canAnnotate(user)

  useEffect(() => {
    api
      .listAnnotations(image.id)
      .then(setAnnotations)
      .catch((err) => setError(api.messageOf(err)))
  }, [image.id])

  function reset() {
    setDragStart(null)
    setDragNow(null)
    setPolygon([])
    setDraft(null)
    setLabel('')
  }

  function chooseTool(next: Tool) {
    reset()
    setError(null)
    setTool(next)
  }

  const finishPolygon = (points: Point[]) => {
    if (points.length < 3) return
    setDraft({ kind: 'polygon', geometry: { points: points.map((p) => [p.x, p.y]) } })
    setPolygon([])
  }

  // Keyboard for the polygon tool: Enter finishes, Escape cancels.
  useEffect(() => {
    if (tool !== 'polygon') return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') reset()
      if (event.key === 'Enter') finishPolygon(polygon)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tool, polygon])

  const at = (event: PointerEvent) => toFraction(event.clientX, event.clientY, svgRef.current!.getBoundingClientRect())

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (draft || tool === 'view') return
    if (tool === 'bbox') {
      event.currentTarget.setPointerCapture(event.pointerId)
      setDragStart(at(event))
      setDragNow(at(event))
    } else {
      const point = at(event)
      if (polygon.length >= 3 && isNear(point, polygon[0])) finishPolygon(polygon)
      else setPolygon([...polygon, point])
    }
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    if (tool === 'bbox' && dragStart) setDragNow(at(event))
  }

  function onPointerUp() {
    if (tool !== 'bbox' || !dragStart || !dragNow) return
    const box = bboxFromPoints(dragStart, dragNow)
    setDragStart(null)
    setDragNow(null)
    if (box.width > 0.005 && box.height > 0.005) setDraft({ kind: 'bbox', geometry: box })
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    try {
      const created = await api.createAnnotation(image.id, { ...draft, label })
      setAnnotations([...annotations, created])
      reset()
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  async function crop(box: BBoxGeometry) {
    setError(null)
    setDuplicateOf(null)
    const region = bboxToPixels(box, image.width, image.height)
    if (!isBigEnoughToCrop(region)) {
      setError(`Crop region must be at least ${CROP_MIN_PX}×${CROP_MIN_PX} px (got ${region.width}×${region.height}).`)
      return
    }
    try {
      const child = await api.cropImage(image.id, region)
      navigate(`/images/${child.id}`)
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 409) {
        setDuplicateOf((err.detail as { image_id: number }).image_id)
      } else {
        setError(api.messageOf(err))
      }
    }
  }

  async function rename(event: FormEvent) {
    event.preventDefault()
    if (!renaming) return
    try {
      const updated = await api.updateAnnotation(renaming.id, { label: renaming.label })
      setAnnotations(annotations.map((a) => (a.id === updated.id ? updated : a)))
      setRenaming(null)
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  async function remove(annotation: Annotation) {
    if (!window.confirm(`Delete annotation "${annotation.label}"?`)) return
    try {
      await api.deleteAnnotation(annotation.id)
      setAnnotations(annotations.filter((a) => a.id !== annotation.id))
    } catch (err) {
      setError(api.messageOf(err))
    }
  }

  const dragBox = dragStart && dragNow ? bboxFromPoints(dragStart, dragNow) : null
  const hint =
    tool === 'bbox'
      ? 'Drag on the image to draw a box.'
      : tool === 'polygon'
        ? 'Click to add points. Click the first point or press Enter to finish; Esc cancels.'
        : null

  return (
    <div className="annotator">
      {mayDraw && (
        <div className="toolbar" role="toolbar" aria-label="Annotation tools">
          {(['view', 'bbox', 'polygon'] as Tool[]).map((t) => (
            <button
              key={t}
              type="button"
              className={tool === t ? '' : 'secondary'}
              aria-pressed={tool === t}
              onClick={() => chooseTool(t)}
            >
              {{ view: 'View', bbox: 'Box', polygon: 'Polygon' }[t]}
            </button>
          ))}
          {hint && <span className="muted small">{hint}</span>}
        </div>
      )}

      <div className="canvas-wrap">
        <AuthImage path={imagePath} alt={image.original_filename} className="full" />
        <svg
          ref={svgRef}
          className={`overlay ${tool !== 'view' ? 'drawing' : ''}`}
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          data-testid="annotation-layer"
        >
          {annotations.map((a) =>
            a.kind === 'bbox' ? (
              <rect
                key={a.id}
                {...(a.geometry as BBoxGeometry)}
                className={`shape ${selected === a.id ? 'selected' : ''}`}
                vectorEffect="non-scaling-stroke"
              />
            ) : (
              <polygon
                key={a.id}
                points={pointsAttr((a.geometry as PolygonGeometry).points)}
                className={`shape ${selected === a.id ? 'selected' : ''}`}
                vectorEffect="non-scaling-stroke"
              />
            ),
          )}
          {dragBox && <rect {...dragBox} className="shape draft" vectorEffect="non-scaling-stroke" />}
          {draft?.kind === 'bbox' && <rect {...draft.geometry} className="shape draft" vectorEffect="non-scaling-stroke" />}
          {draft?.kind === 'polygon' && (
            <polygon points={pointsAttr(draft.geometry.points)} className="shape draft" vectorEffect="non-scaling-stroke" />
          )}
          {polygon.length > 0 && (
            <polyline
              points={pointsAttr(polygon.map((p) => [p.x, p.y]))}
              className="shape draft open"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
        {annotations.map((a, i) => {
          const { x, y } = labelAnchor(a)
          return (
            <span key={a.id} className="shape-label" style={{ left: `${x * 100}%`, top: `${y * 100}%` }}>
              {i + 1}. {a.label}
            </span>
          )
        })}
      </div>

      {draft && (
        <form className="draft-form" onSubmit={save}>
          <label>
            Label for this {draft.kind === 'bbox' ? 'box' : 'polygon'}
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. rust pustule" maxLength={100} required autoFocus />
          </label>
          <div className="actions">
            <button type="submit">Save annotation</button>
            {draft.kind === 'bbox' && (
              <button type="button" className="secondary" onClick={() => crop(draft.geometry)}>
                Crop to new image
              </button>
            )}
            <button type="button" className="secondary" onClick={reset}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <ErrorMessage error={error} />
      {duplicateOf !== null && (
        <p className="error" role="alert">
          This crop already exists as <Link to={`/images/${duplicateOf}`}>image #{duplicateOf}</Link>.
        </p>
      )}

      <h3>Annotations ({annotations.length})</h3>
      {annotations.length === 0 && <p className="muted small">No annotations yet.</p>}
      <ol className="annotation-list">
        {annotations.map((a) => {
          const mayEdit = canEditAnnotation(user, a)
          return (
            <li
              key={a.id}
              onMouseEnter={() => setSelected(a.id)}
              onMouseLeave={() => setSelected(null)}
              className={selected === a.id ? 'selected' : ''}
            >
              {renaming?.id === a.id ? (
                <form className="inline-form" onSubmit={rename}>
                  <input
                    value={renaming.label}
                    onChange={(e) => setRenaming({ id: a.id, label: e.target.value })}
                    maxLength={100}
                    required
                    autoFocus
                    aria-label="New label"
                  />
                  <button type="submit">Save</button>
                  <button type="button" className="secondary" onClick={() => setRenaming(null)}>
                    Cancel
                  </button>
                </form>
              ) : (
                <>
                  <span>
                    <strong>{a.label}</strong> <span className="muted small">{a.kind} · by user #{a.created_by}</span>
                  </span>
                  <span className="list-actions">
                    {a.kind === 'bbox' && mayDraw && (
                      <button type="button" className="link-button" onClick={() => crop(a.geometry as BBoxGeometry)}>
                        Crop
                      </button>
                    )}
                    {mayEdit && (
                      <>
                        <button type="button" className="link-button" onClick={() => setRenaming({ id: a.id, label: a.label })}>
                          Rename
                        </button>
                        <button type="button" className="link-button danger-link" onClick={() => remove(a)}>
                          Delete
                        </button>
                      </>
                    )}
                  </span>
                </>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
