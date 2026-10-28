// A phone photo becomes a small, upright, cropped, high-contrast grayscale
// JPEG before upload: far less to send, and Tesseract reads it better.

import { applyOrientation, readOrientation, swapsAxes } from './exif';
import { findPaper, levels, toGray, type Rect } from './autocrop';

export const MAX_EDGE = 2000;
const DETECT_EDGE = 360;

export interface Prepared {
  /** The upright, downscaled photo, in color, for the crop screen. */
  canvas: HTMLCanvasElement;
  /** Suggested crop in canvas pixels; the whole image when none was found. */
  crop: Rect;
  autoCropped: boolean;
}

function canvas(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

function ctx2d(c: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas is unavailable in this browser');
  return ctx;
}

// Browsers that honour image-orientation also honour EXIF when decoding.
const browserRotates = typeof CSS !== 'undefined' && CSS.supports?.('image-orientation', 'from-image');

async function decode(file: Blob): Promise<{ source: CanvasImageSource; w: number; h: number; orientation: number }> {
  const orientation = browserRotates ? 1 : await readOrientation(file);
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    return { source: bmp, w: bmp.width, h: bmp.height, orientation };
  } catch {
    // Fallback for decoders createImageBitmap lacks (some HEIC paths on iOS).
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      return { source: img, w: img.naturalWidth, h: img.naturalHeight, orientation };
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}

export async function prepare(file: Blob): Promise<Prepared> {
  const { source, w, h, orientation } = await decode(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
  const sw = Math.round(w * scale);
  const sh = Math.round(h * scale);
  const swap = swapsAxes(orientation);
  const out = canvas(swap ? sh : sw, swap ? sw : sh);
  const ctx = ctx2d(out);
  applyOrientation(ctx, orientation, sw, sh);
  ctx.drawImage(source, 0, 0, sw, sh);
  if ('close' in source) (source as ImageBitmap).close();

  const crop = detect(out);
  return {
    canvas: out,
    crop: crop ?? { x: 0, y: 0, w: out.width, h: out.height },
    autoCropped: crop !== null,
  };
}

/** Run the paper finder on a small copy and scale its answer back up. */
function detect(full: HTMLCanvasElement): Rect | null {
  const k = Math.min(1, DETECT_EDGE / Math.max(full.width, full.height));
  const small = canvas(Math.max(1, Math.round(full.width * k)), Math.max(1, Math.round(full.height * k)));
  const sctx = ctx2d(small);
  sctx.drawImage(full, 0, 0, small.width, small.height);
  const gray = toGray(sctx.getImageData(0, 0, small.width, small.height).data);
  const r = findPaper(gray, small.width, small.height);
  if (!r) return null;
  return {
    x: Math.round(r.x / k),
    y: Math.round(r.y / k),
    w: Math.min(full.width, Math.round(r.w / k)),
    h: Math.min(full.height, Math.round(r.h / k)),
  };
}

/** Crop, grayscale and level the photo, then encode it as a JPEG. */
export async function finish(prepared: Prepared, crop: Rect, enhance = true): Promise<Blob> {
  const x = Math.max(0, Math.round(crop.x));
  const y = Math.max(0, Math.round(crop.y));
  const w = Math.min(prepared.canvas.width - x, Math.round(crop.w));
  const h = Math.min(prepared.canvas.height - y, Math.round(crop.h));
  const out = canvas(w, h);
  const ctx = ctx2d(out);
  ctx.drawImage(prepared.canvas, x, y, w, h, 0, 0, w, h);
  if (enhance) {
    const img = ctx.getImageData(0, 0, w, h);
    const gray = levels(toGray(img.data));
    for (let i = 0, j = 0; j < gray.length; i += 4, j++) {
      img.data[i] = img.data[i + 1] = img.data[i + 2] = gray[j];
    }
    ctx.putImageData(img, 0, 0);
  }
  return new Promise((resolve, reject) =>
    out.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not encode the image'))), 'image/jpeg', 0.85),
  );
}
