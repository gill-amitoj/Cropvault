// Pure helpers for annotation coordinates. Everything stored is a fraction (0-1) of the image
// as displayed (trap #9); pixels are only used for the crop request.
import type { BBoxGeometry } from './types'

export interface Point {
  x: number
  y: number
}

export const CROP_MIN_PX = 16 // must match images.CROP_MIN_SIZE in the backend

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))

/** Keep 5 decimals: 0.00001 of a 10,000 px image is 0.1 px, and the JSON stays readable. */
export const round5 = (v: number) => Math.round(v * 100000) / 100000

/** Pointer position -> fraction of the element (0-1), clamped to its edges. */
export function toFraction(clientX: number, clientY: number, rect: DOMRect): Point {
  return {
    x: round5(clamp01((clientX - rect.left) / rect.width)),
    y: round5(clamp01((clientY - rect.top) / rect.height)),
  }
}

/** Box from two corners, whichever direction the user dragged. */
export function bboxFromPoints(a: Point, b: Point): BBoxGeometry {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: round5(Math.abs(b.x - a.x)),
    height: round5(Math.abs(b.y - a.y)),
  }
}

// Float maths gives e.g. (0.101 + 0.2) * 1000 = 301.00000000000006; without a tolerance,
// rounding up would add a whole extra pixel.
const FLOAT_TOLERANCE = 1e-6

/** Fractions -> whole pixels of the real image, never outside it (for the crop endpoint).
 *  Rounds outward so the crop covers the whole drawn box. */
export function bboxToPixels(box: BBoxGeometry, imageWidth: number, imageHeight: number) {
  const x = Math.floor(box.x * imageWidth + FLOAT_TOLERANCE)
  const y = Math.floor(box.y * imageHeight + FLOAT_TOLERANCE)
  const right = Math.min(imageWidth, Math.ceil((box.x + box.width) * imageWidth - FLOAT_TOLERANCE))
  const bottom = Math.min(imageHeight, Math.ceil((box.y + box.height) * imageHeight - FLOAT_TOLERANCE))
  return { x, y, width: right - x, height: bottom - y }
}

export const isBigEnoughToCrop = (px: { width: number; height: number }) =>
  px.width >= CROP_MIN_PX && px.height >= CROP_MIN_PX

/** Close enough to the first polygon point to finish the shape by clicking it. */
export const isNear = (a: Point, b: Point, tolerance = 0.02) =>
  Math.abs(a.x - b.x) <= tolerance && Math.abs(a.y - b.y) <= tolerance
