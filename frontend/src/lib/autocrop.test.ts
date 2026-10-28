import { describe, expect, it } from 'vitest';
import { findPaper, levels, otsu, histogram } from './autocrop';

/** A dark w×h background with a bright rectangle (the receipt). */
function scene(w: number, h: number, paper: { x: number; y: number; w: number; h: number }, bg = 60, fg = 220) {
  const g = new Uint8Array(w * h).fill(bg);
  for (let y = paper.y; y < paper.y + paper.h; y++)
    for (let x = paper.x; x < paper.x + paper.w; x++) g[y * w + x] = fg;
  // Some "print" on the paper.
  for (let y = paper.y + 10; y < paper.y + paper.h - 10; y += 8)
    for (let x = paper.x + 6; x < paper.x + paper.w - 6; x += 3) g[y * w + x] = 30;
  return g;
}

describe('findPaper', () => {
  it('finds a tall receipt on a dark table', () => {
    const r = findPaper(scene(300, 400, { x: 100, y: 40, w: 90, h: 320 }), 300, 400);
    expect(r).not.toBeNull();
    expect(Math.abs(r!.x - 100)).toBeLessThanOrEqual(8);
    expect(Math.abs(r!.y - 40)).toBeLessThanOrEqual(8);
    expect(Math.abs(r!.x + r!.w - 190)).toBeLessThanOrEqual(8);
    expect(Math.abs(r!.y + r!.h - 360)).toBeLessThanOrEqual(8);
  });

  it('leaves an already-cropped scan alone', () => {
    expect(findPaper(scene(200, 400, { x: 0, y: 0, w: 200, h: 400 }), 200, 400)).toBeNull();
  });

  it('gives up on a blank frame', () => {
    expect(findPaper(new Uint8Array(100 * 100).fill(40), 100, 100)).toBeNull();
  });
});

describe('levels', () => {
  it('stretches faded print to full contrast', () => {
    const g = new Uint8Array(1000);
    for (let i = 0; i < 1000; i++) g[i] = i % 10 === 0 ? 120 : 180;
    const out = levels(g);
    expect(Math.min(...out)).toBe(0);
    expect(Math.max(...out)).toBe(255);
  });
});

describe('otsu', () => {
  it('splits two clusters', () => {
    const g = new Uint8Array(200);
    g.fill(50, 0, 100);
    g.fill(200, 100);
    const t = otsu(histogram(g));
    expect(t).toBeGreaterThanOrEqual(50);
    expect(t).toBeLessThan(200);
  });
});
