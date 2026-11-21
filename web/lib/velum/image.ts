/** An 8-bit RGB image in memory: the only pixel type VELUM works with (VELUM.md section 3). */

export const MAX_SIDE = 16384 // pixels; bounds memory for anything a file can make us allocate

export interface Image {
  readonly width: number
  readonly height: number
  /** width * height pixels, row by row from the top, 3 bytes each (R, G, B). */
  readonly rgb: Uint8Array
}

export function makeImage(width: number, height: number, rgb: Uint8Array): Image {
  if (!(Number.isInteger(width) && Number.isInteger(height) && width >= 1 && height >= 1 && width <= MAX_SIDE && height <= MAX_SIDE)) {
    throw new RangeError(`image size ${width}x${height} outside 1..${MAX_SIDE}`)
  }
  if (rgb.length !== width * height * 3) throw new RangeError('pixel buffer length does not match width * height * 3')
  return { width, height, rgb }
}
