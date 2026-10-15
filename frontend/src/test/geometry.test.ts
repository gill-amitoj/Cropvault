import { describe, expect, it } from 'vitest'

import { bboxFromPoints, bboxToPixels, isBigEnoughToCrop, isNear, round5, toFraction } from '../geometry'

const rect = { left: 100, top: 50, width: 400, height: 200 } as DOMRect

describe('toFraction', () => {
  it('turns a pointer position into fractions of the element', () => {
    expect(toFraction(300, 150, rect)).toEqual({ x: 0.5, y: 0.5 })
    expect(toFraction(100, 50, rect)).toEqual({ x: 0, y: 0 })
  })

  it('clamps positions outside the element to its edges', () => {
    expect(toFraction(0, 999, rect)).toEqual({ x: 0, y: 1 })
  })

  it('gives the same fraction at any display size (trap #9)', () => {
    const small = { left: 0, top: 0, width: 320, height: 240 } as DOMRect
    const large = { left: 0, top: 0, width: 1280, height: 960 } as DOMRect
    expect(toFraction(80, 60, small)).toEqual(toFraction(320, 240, large))
  })
})

describe('bboxFromPoints', () => {
  it('works whichever direction the user drags', () => {
    const expected = { x: 0.2, y: 0.1, width: 0.3, height: 0.4 }
    expect(bboxFromPoints({ x: 0.2, y: 0.1 }, { x: 0.5, y: 0.5 })).toEqual(expected)
    expect(bboxFromPoints({ x: 0.5, y: 0.5 }, { x: 0.2, y: 0.1 })).toEqual(expected)
  })
})

describe('bboxToPixels', () => {
  it('converts fractions to whole pixels of the real image', () => {
    expect(bboxToPixels({ x: 0.5, y: 0, width: 0.5, height: 1 }, 200, 100)).toEqual({
      x: 100,
      y: 0,
      width: 100,
      height: 100,
    })
  })

  it('never goes outside the image, even with float rounding', () => {
    const px = bboxToPixels({ x: 0.3, y: 0.3, width: 0.7, height: 0.7 }, 1280, 960)
    expect(px.x + px.width).toBeLessThanOrEqual(1280)
    expect(px.y + px.height).toBeLessThanOrEqual(960)
  })

  it('rounds outward so the crop covers the whole drawn box', () => {
    expect(bboxToPixels({ x: 0.101, y: 0.101, width: 0.2, height: 0.2 }, 1000, 1000)).toEqual({
      x: 101,
      y: 101,
      width: 200,
      height: 200,
    })
  })
})

describe('small helpers', () => {
  it('enforces the 16 px crop minimum', () => {
    expect(isBigEnoughToCrop({ width: 16, height: 16 })).toBe(true)
    expect(isBigEnoughToCrop({ width: 15, height: 40 })).toBe(false)
  })

  it('detects a click near the first polygon point', () => {
    expect(isNear({ x: 0.5, y: 0.5 }, { x: 0.51, y: 0.49 })).toBe(true)
    expect(isNear({ x: 0.5, y: 0.5 }, { x: 0.6, y: 0.5 })).toBe(false)
  })

  it('round5 keeps five decimals', () => {
    expect(round5(0.123456789)).toBe(0.12346)
  })
})
