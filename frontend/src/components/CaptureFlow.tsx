// Snap or pick receipts, straighten and crop them, upload. A receipt is filed
// on its own once it's read; tags picked here (HSA, ...) go with it.
//
// Over plain HTTP (the default) the phone's own camera opens through
// <input capture>. Over HTTPS, if it's set up, there's a live viewfinder.

import { useEffect, useRef, useState } from 'preact/hooks';
import { uploadFiles } from '../api';
import { finish, prepare, type Prepared } from '../lib/preprocess';
import type { Rect } from '../lib/autocrop';
import { useStore } from '../store';
import { Icon, Spinner } from './ui';

type Step = 'choose' | 'crop' | 'uploading';

const canLiveCamera = () => window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

export function CaptureFlow() {
  const store = useStore();
  const [step, setStep] = useState<Step>('choose');
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [crop, setCrop] = useState<Rect | null>(null);
  const [enhance, setEnhance] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [sent, setSent] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const snapRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setStep('choose');
    setPrepared(null);
    setCrop(null);
    setBusy(null);
  };

  const close = () => {
    reset();
    store.closeCapture();
    if (sent.length) store.bump();
    setSent([]);
    setTags([]);
  };

  async function onPhoto(blob: Blob) {
    setBusy('Preparing…');
    try {
      const p = await prepare(blob);
      setPrepared(p);
      setCrop(p.crop);
      setStep('crop');
    } catch (e) {
      store.toast(`Couldn't open that image: ${(e as Error).message}`, 'error');
    } finally {
      setBusy(null);
    }
  }

  async function onFiles(list: FileList | null) {
    if (!list || !list.length) return;
    const files = Array.from(list);
    if (files.length === 1 && files[0].type.startsWith('image/')) return onPhoto(files[0]);
    // Several at once (or PDFs): auto-crop and send without stopping at each.
    setStep('uploading');
    const blobs: Blob[] = [];
    const names: string[] = [];
    for (const [i, f] of files.entries()) {
      setBusy(`Preparing ${i + 1} of ${files.length}…`);
      if (f.type === 'application/pdf') {
        blobs.push(f);
        names.push(f.name);
        continue;
      }
      try {
        const p = await prepare(f);
        blobs.push(await finish(p, p.crop, true));
        names.push(f.name.replace(/\.\w+$/, '') + '.jpg');
      } catch {
        store.toast(`Skipped ${f.name}: not an image this browser can open`, 'error');
      }
    }
    await send(blobs, names, true);
  }

  async function send(blobs: Blob[], names: string[], thenClose: boolean) {
    if (!blobs.length) return reset();
    setStep('uploading');
    setBusy(`Uploading ${blobs.length > 1 ? `${blobs.length} receipts` : 'receipt'}…`);
    setProgress(0);
    try {
      const res = await uploadFiles(blobs, names, setProgress, tags);
      const ids = res.receipts.map((r) => r.id);
      const all = [...sent, ...ids];
      setSent(all);
      store.bump();
      if (thenClose) {
        close();
        store.toast(all.length === 1 ? 'Saved. It’s filed as soon as it’s read.' : `Saved ${all.length} receipts. They’re filed as soon as they’re read.`);
      } else {
        store.toast(`Saved. ${all.length} so far; scan the next one.`);
        reset();
      }
    } catch (e) {
      store.toast((e as Error).message, 'error');
      setStep(prepared ? 'crop' : 'choose');
      setBusy(null);
    }
  }

  async function useImage(next: boolean) {
    if (!prepared || !crop) return;
    setBusy('Enhancing…');
    const blob = await finish(prepared, crop, enhance);
    await send([blob], [`receipt-${Date.now()}.jpg`], !next);
  }

  if (!store.captureOpen) return null;

  return (
    <div class="fixed inset-0 z-50 flex flex-col bg-neutral-950 text-white">
      <div class="flex items-center justify-between px-3 pt-[max(env(safe-area-inset-top),0.75rem)] pb-2">
        <button class="btn btn-ghost px-2 text-white" onClick={close} aria-label="Close">
          <Icon name="x" />
        </button>
        <span class="text-sm font-medium">
          {step === 'crop' ? 'Adjust the crop' : 'Scan a receipt'}
          {sent.length > 0 && <span class="ml-2 text-neutral-400">· {sent.length} saved</span>}
        </span>
        {sent.length > 0 ? (
          <button class="btn btn-ghost px-2 text-white" onClick={close}>
            Done
          </button>
        ) : (
          <span class="w-10" />
        )}
      </div>

      <input ref={fileRef} type="file" accept="image/*,application/pdf" multiple class="hidden" onChange={(e) => onFiles((e.target as HTMLInputElement).files)} />
      <input ref={snapRef} type="file" accept="image/*" capture="environment" class="hidden" onChange={(e) => onFiles((e.target as HTMLInputElement).files)} />

      {step === 'choose' && canLiveCamera() && (
        <div class="px-4 pb-2">
          <TagPicker value={tags} onChange={setTags} />
        </div>
      )}

      {step === 'choose' &&
        (canLiveCamera() ? (
          <LiveCamera onShot={onPhoto} onPick={() => fileRef.current?.click()} busy={busy} />
        ) : (
          <div class="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
            <button class="btn btn-primary h-14 w-full max-w-xs text-base" onClick={() => snapRef.current?.click()} disabled={!!busy}>
              <Icon name="camera" /> Take a photo
            </button>
            <button class="btn h-12 w-full max-w-xs border-neutral-700 bg-neutral-800 text-white" onClick={() => fileRef.current?.click()} disabled={!!busy}>
              <Icon name="image" /> Choose photos or PDFs
            </button>
            <TagPicker value={tags} onChange={setTags} />
            {busy && <p class="flex items-center gap-2 text-sm text-neutral-300"><Spinner /> {busy}</p>}
          </div>
        ))}

      {step === 'crop' && prepared && crop && (
        <>
          <CropBox prepared={prepared} crop={crop} onChange={setCrop} enhance={enhance} />
          <div class="safe-bottom flex flex-col gap-3 px-4 pt-2 pb-4">
            <TagPicker value={tags} onChange={setTags} />
            <div class="flex items-center justify-between text-xs text-neutral-300">
              <button class="underline" onClick={() => setCrop({ x: 0, y: 0, w: prepared.canvas.width, h: prepared.canvas.height })}>
                Use the whole photo
              </button>
              <label class="flex items-center gap-2">
                <input type="checkbox" checked={enhance} onChange={(e) => setEnhance((e.target as HTMLInputElement).checked)} />
                Black &amp; white boost
              </label>
            </div>
            <div class="grid grid-cols-3 gap-2">
              <button class="btn border-neutral-700 bg-neutral-800 text-white" onClick={reset} disabled={!!busy}>
                Retake
              </button>
              <button class="btn border-neutral-700 bg-neutral-800 text-white" onClick={() => useImage(true)} disabled={!!busy}>
                Save + next
              </button>
              <button class="btn btn-primary" onClick={() => useImage(false)} disabled={!!busy}>
                {busy ? <Spinner /> : <Icon name="check" />} Save
              </button>
            </div>
          </div>
        </>
      )}

      {step === 'uploading' && (
        <div class="flex flex-1 flex-col items-center justify-center gap-4 p-6">
          <Spinner class="h-8 w-8" />
          <p class="text-sm">{busy}</p>
          {progress > 0 && (
            <div class="h-1.5 w-48 overflow-hidden rounded-full bg-neutral-800">
              <div class="h-full bg-brand-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LiveCamera(props: { onShot: (b: Blob) => void; onPick: () => void; busy: string | null }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [torch, setTorch] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);

  useEffect(() => {
    let active: MediaStream | null = null;
    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } },
      })
      .then((s) => {
        active = s;
        setStream(s);
        if (videoRef.current) videoRef.current.srcObject = s;
        const caps = s.getVideoTracks()[0]?.getCapabilities?.() as MediaTrackCapabilities & { torch?: boolean };
        setTorchAvailable(!!caps?.torch);
      })
      .catch((e: Error) => setError(e.name === 'NotAllowedError' ? 'Camera permission was denied.' : e.message));
    return () => active?.getTracks().forEach((t) => t.stop());
  }, []);

  const toggleTorch = async () => {
    const track = stream?.getVideoTracks()[0];
    if (!track) return;
    const next = !torch;
    await track.applyConstraints({ advanced: [{ torch: next } as MediaTrackConstraintSet] }).catch(() => {});
    setTorch(next);
  };

  const shoot = async () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const c = document.createElement('canvas');
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    c.getContext('2d')!.drawImage(video, 0, 0);
    c.toBlob((b) => b && props.onShot(b), 'image/jpeg', 0.92);
  };

  return (
    <div class="relative flex flex-1 flex-col">
      {error ? (
        <div class="flex flex-1 items-center justify-center p-6 text-center text-sm text-neutral-300">
          {error} You can still choose photos from the gallery.
        </div>
      ) : (
        <div class="relative flex-1 overflow-hidden">
          <video ref={videoRef} autoplay playsinline muted class="absolute inset-0 h-full w-full object-cover" />
          {/* A guide for framing a tall receipt. */}
          <div class="pointer-events-none absolute inset-x-[18%] inset-y-[8%] rounded-2xl border-2 border-dashed border-white/50" />
          {props.busy && (
            <div class="absolute inset-0 flex items-center justify-center bg-black/50">
              <Spinner class="h-8 w-8" />
            </div>
          )}
        </div>
      )}
      <div class="safe-bottom flex items-center justify-around px-6 py-4">
        <button class="btn btn-ghost flex-col gap-1 text-xs text-white" onClick={props.onPick}>
          <Icon name="image" /> Gallery
        </button>
        <button
          class="h-18 w-18 rounded-full border-4 border-white bg-white/20 transition active:scale-95 disabled:opacity-40"
          style={{ width: '4.5rem', height: '4.5rem' }}
          onClick={shoot}
          disabled={!stream || !!props.busy}
          aria-label="Take photo"
        />
        <button
          class={`btn btn-ghost flex-col gap-1 text-xs ${torch ? 'text-yellow-300' : 'text-white'}`}
          onClick={toggleTorch}
          disabled={!torchAvailable}
        >
          <Icon name="bolt" /> Light
        </button>
      </div>
    </div>
  );
}

/** The photo with a draggable crop rectangle: drag a corner or the middle. */
function CropBox(props: { prepared: Prepared; crop: Rect; onChange: (r: Rect) => void; enhance: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLCanvasElement>(null);
  const [scale, setScale] = useState(1);
  const drag = useRef<{ handle: string; startX: number; startY: number; start: Rect } | null>(null);
  const { canvas } = props.prepared;

  useEffect(() => {
    const target = imgRef.current;
    if (!target) return;
    const fit = () => {
      const wrap = wrapRef.current!;
      const s = Math.min((wrap.clientWidth - 24) / canvas.width, (wrap.clientHeight - 24) / canvas.height);
      setScale(s);
      target.width = Math.round(canvas.width * s);
      target.height = Math.round(canvas.height * s);
      target.getContext('2d')!.drawImage(canvas, 0, 0, target.width, target.height);
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [canvas]);

  const onDown = (handle: string) => (e: PointerEvent) => {
    e.preventDefault();
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { handle, startX: e.clientX, startY: e.clientY, start: { ...props.crop } };
  };

  const onMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = (e.clientX - d.startX) / scale;
    const dy = (e.clientY - d.startY) / scale;
    const W = canvas.width;
    const H = canvas.height;
    const min = 60;
    let { x, y, w, h } = d.start;
    if (d.handle === 'move') {
      x = Math.min(Math.max(0, x + dx), W - w);
      y = Math.min(Math.max(0, y + dy), H - h);
    } else {
      if (d.handle.includes('l')) {
        const nx = Math.min(Math.max(0, x + dx), x + w - min);
        w += x - nx;
        x = nx;
      }
      if (d.handle.includes('r')) w = Math.min(Math.max(min, w + dx), W - x);
      if (d.handle.includes('t')) {
        const ny = Math.min(Math.max(0, y + dy), y + h - min);
        h += y - ny;
        y = ny;
      }
      if (d.handle.includes('b')) h = Math.min(Math.max(min, h + dy), H - y);
    }
    props.onChange({ x, y, w, h });
  };

  const c = props.crop;
  const box = { left: c.x * scale, top: c.y * scale, width: c.w * scale, height: c.h * scale };
  const handle = 'absolute h-7 w-7 rounded-full border-2 border-white bg-brand-600 shadow touch-none';

  return (
    <div ref={wrapRef} class="relative flex flex-1 items-center justify-center overflow-hidden" onPointerMove={onMove} onPointerUp={() => (drag.current = null)}>
      <div class="relative">
        <canvas ref={imgRef} class={props.enhance ? 'grayscale contrast-125' : ''} />
        {/* Dim what's cut away. */}
        <div class="pointer-events-none absolute inset-0" style={{ boxShadow: 'none' }}>
          <div
            class="absolute border-2 border-brand-500"
            style={{ ...px(box), boxShadow: '0 0 0 9999px rgba(2,6,23,.6)' }}
          />
        </div>
        <div class="absolute touch-none" style={px(box)} onPointerDown={onDown('move')} />
        {(['tl', 'tr', 'bl', 'br'] as const).map((hnd) => (
          <div
            key={hnd}
            class={handle}
            style={{
              left: `${box.left + (hnd.includes('r') ? box.width : 0) - 14}px`,
              top: `${box.top + (hnd.includes('b') ? box.height : 0) - 14}px`,
            }}
            onPointerDown={onDown(hnd)}
          />
        ))}
      </div>
    </div>
  );
}

const px = (b: { left: number; top: number; width: number; height: number }) => ({
  left: `${b.left}px`,
  top: `${b.top}px`,
  width: `${b.width}px`,
  height: `${b.height}px`,
});

/** "What's this for?": the tax-relevant tags, picked before saving. */
function TagPicker(props: { value: string[]; onChange: (v: string[]) => void }) {
  const { tags } = useStore();
  const order = ['hsa', 'donation', 'warranty'];
  const kinds = tags.filter((t) => t.kind !== 'plain').sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  if (!kinds.length) return null;
  return (
    <div class="flex flex-wrap items-center justify-center gap-2" role="group" aria-label="Tag this receipt">
      <span class="text-xs text-neutral-400">Tag it:</span>
      {kinds.map((t) => {
        const on = props.value.includes(t.name);
        return (
          <button
            key={t.name}
            aria-pressed={on}
            class={`min-h-9 rounded-full border px-3.5 text-sm ${on ? 'border-white bg-white text-neutral-900' : 'border-neutral-600 text-neutral-200'}`}
            onClick={() => props.onChange(on ? props.value.filter((x) => x !== t.name) : [...props.value, t.name])}
          >
            {t.name}
          </button>
        );
      })}
    </div>
  );
}
