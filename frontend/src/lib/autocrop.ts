// Finding the receipt in a photo, and evening out its contrast. Pure
// functions over grayscale pixels so they can be tested without a canvas.

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function toGray(rgba: Uint8ClampedArray): Uint8Array {
  const out = new Uint8Array(rgba.length / 4);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j++) {
    // Rec. 601 luma, integer maths.
    out[j] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8;
  }
  return out;
}

export function histogram(gray: Uint8Array): Uint32Array {
  const h = new Uint32Array(256);
  for (let i = 0; i < gray.length; i++) h[gray[i]]++;
  return h;
}

/** Otsu's threshold: the gray level that best splits paper from background. */
export function otsu(hist: Uint32Array): number {
  let total = 0;
  let sum = 0;
  for (let i = 0; i < 256; i++) {
    total += hist[i];
    sum += i * hist[i];
  }
  let sumB = 0;
  let wB = 0;
  let best = 0;
  let threshold = 127;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = total - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const mB = sumB / wB;
    const mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) ** 2;
    if (between > best) {
      best = between;
      threshold = t;
    }
  }
  return threshold;
}

function span(fractions: Float32Array, cutoff: number): [number, number] | null {
  let lo = -1;
  let hi = -1;
  for (let i = 0; i < fractions.length; i++) {
    if (fractions[i] >= cutoff) {
      if (lo < 0) lo = i;
      hi = i;
    }
  }
  return lo < 0 ? null : [lo, hi];
}

/**
 * The bright paper's bounding box in a w×h grayscale image, or null when the
 * photo is already just the receipt (or no clear paper stands out).
 *
 * Paper is the bright side of an Otsu split. Columns come first, because a
 * receipt is tall: its columns are mostly paper. Rows are then measured only
 * inside those columns.
 */
export function findPaper(gray: Uint8Array, w: number, h: number): Rect | null {
  const t = otsu(histogram(gray));
  const bright = (i: number) => gray[i] > t;

  const cols = new Float32Array(w);
  for (let x = 0; x < w; x++) {
    let n = 0;
    for (let y = 0; y < h; y++) if (bright(y * w + x)) n++;
    cols[x] = n / h;
  }
  const maxCol = Math.max(...cols);
  if (maxCol < 0.2) return null;
  const xs = span(cols, maxCol * 0.5);
  if (!xs) return null;

  const width = xs[1] - xs[0] + 1;
  const rows = new Float32Array(h);
  for (let y = 0; y < h; y++) {
    let n = 0;
    for (let x = xs[0]; x <= xs[1]; x++) if (bright(y * w + x)) n++;
    rows[y] = n / width;
  }
  const maxRow = Math.max(...rows);
  const ys = span(rows, maxRow * 0.5);
  if (!ys) return null;

  const pad = Math.round(Math.max(w, h) * 0.015);
  const rect = {
    x: Math.max(0, xs[0] - pad),
    y: Math.max(0, ys[0] - pad),
    w: 0,
    h: 0,
  };
  rect.w = Math.min(w, xs[1] + pad + 1) - rect.x;
  rect.h = Math.min(h, ys[1] + pad + 1) - rect.y;

  const share = (rect.w * rect.h) / (w * h);
  if (share > 0.92 || share < 0.08) return null;
  return rect;
}

/** Stretch levels so the darkest `lo` and brightest `hi` fractions clip:
 * faded thermal print comes out black on white. */
export function levels(gray: Uint8Array, lo = 0.02, hi = 0.98): Uint8Array {
  const hist = histogram(gray);
  const n = gray.length;
  let acc = 0;
  let black = 0;
  let white = 255;
  for (let i = 0; i < 256; i++) {
    acc += hist[i];
    if (acc >= n * lo) {
      black = i;
      break;
    }
  }
  acc = 0;
  for (let i = 255; i >= 0; i--) {
    acc += hist[i];
    if (acc >= n * (1 - hi)) {
      white = i;
      break;
    }
  }
  if (white - black < 16) return gray;
  const lut = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    lut[i] = Math.max(0, Math.min(255, Math.round(((i - black) * 255) / (white - black))));
  }
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = lut[gray[i]];
  return out;
}
