// Confirm what OCR read: the image beside the fields, Confirm to file it.

import { useEffect, useState } from 'preact/hooks';
import { api, previewUrl, type Receipt } from '../api';
import { useStore } from '../store';
import { ReceiptEditor, kindsOf, toDraft, toPatch, useReceipt, type Draft } from './ReceiptEditor';
import { Icon, Modal, Spinner } from './ui';
import { useLocation } from 'preact-iso';

export function ReviewModal() {
  const store = useStore();
  const { route } = useLocation();
  const id = store.reviewId;
  const { receipt, setReceipt, error } = useReceipt(id);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [zoom, setZoom] = useState(false);

  const reading = receipt && (receipt.status === 'queued' || receipt.status === 'processing');

  useEffect(() => {
    setDraft(null);
    setZoom(false);
  }, [id]);

  useEffect(() => {
    // Fill the form once the reading is done, without clobbering edits.
    if (receipt && receipt.id === id && !reading && !draft) setDraft(toDraft(receipt));
  }, [receipt, reading]);

  if (!id) return null;

  const next = () => {
    const q = store.reviewQueue;
    const i = q.indexOf(id);
    const after = q.slice(i + 1).find(Boolean);
    if (after) store.openReview(after, q);
    else store.closeReview();
  };

  const save = async (status?: 'confirmed') => {
    if (!receipt || !draft) return;
    setSaving(true);
    try {
      const patch = toPatch(draft, receipt, kindsOf(draft, store.tags));
      if (status) patch.status = status;
      const updated = await api.patch<Receipt>(`/api/receipts/${receipt.id}`, patch);
      setReceipt(updated);
      store.bump();
      if (status === 'confirmed') {
        store.toast(`Filed ${updated.merchant ?? 'receipt'} under ${updated.category ?? 'Other'}`);
        next();
      } else {
        store.toast('Saved');
      }
    } catch (e) {
      store.toast((e as Error).message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!receipt || !confirm('Delete this receipt? Its files move to the trash folder.')) return;
    await api.del(`/api/receipts/${receipt.id}`);
    store.bump();
    store.toast('Deleted');
    next();
  };

  const position = store.reviewQueue.length > 1 ? `${store.reviewQueue.indexOf(id) + 1} of ${store.reviewQueue.length}` : '';

  return (
    <Modal
      open
      wide
      onClose={store.closeReview}
      title={receipt?.status === 'confirmed' ? 'Edit receipt' : `Needs a look ${position && `· ${position}`}`}
      footer={
        draft &&
        receipt && (
          <div class="flex items-center gap-2">
            <button class="btn btn-danger btn-ghost px-3" onClick={remove} aria-label="Delete" title="Delete" disabled={saving}>
              <Icon name="trash" size={18} />
            </button>
            <button
              class="btn btn-ghost px-3"
              onClick={() => {
                store.closeReview();
                route(`/receipts/${receipt.id}`);
              }}
            >
              Details
            </button>
            <div class="flex-1" />
            {receipt.status !== 'confirmed' && store.reviewQueue.length > 1 && (
              <button class="btn" onClick={next} disabled={saving}>
                Skip
              </button>
            )}
            <button class="btn btn-primary" onClick={() => save('confirmed')} disabled={saving}>
              {saving ? <Spinner /> : <Icon name="check" size={18} />}
              {receipt.status === 'confirmed' ? 'Save' : 'File it'}
            </button>
          </div>
        )
      }
    >
      {error && <p class="p-4 text-red-600">{error}</p>}
      {!receipt && !error && (
        <div class="flex justify-center p-10">
          <Spinner />
        </div>
      )}
      {receipt && (
        <div class="grid gap-4 p-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div class="sm:sticky sm:top-0 sm:self-start">
            <button
              class={`relative block w-full overflow-hidden rounded-2xl bg-neutral-100 dark:bg-neutral-800 ${zoom ? '' : 'max-h-56 sm:max-h-[70vh]'}`}
              onClick={() => setZoom(!zoom)}
              aria-label={zoom ? 'Shrink image' : 'Enlarge image'}
            >
              <img src={previewUrl(receipt, 1200)} alt="Receipt" class={`w-full ${zoom ? '' : 'object-cover object-top sm:object-contain'}`} />
              <span class="absolute right-2 bottom-2 rounded-full bg-black/50 p-1.5 text-white">
                <Icon name="zoom" size={16} />
              </span>
            </button>
            {receipt.ocr_confidence !== null && !reading && (
              <p class="muted mt-1 text-xs">Read with {Math.round(receipt.ocr_confidence)}% confidence</p>
            )}
            {receipt.status === 'failed' && (
              <p class="mt-2 rounded-xl bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
                Couldn’t read it: {receipt.error}. Fill the fields in by hand.
              </p>
            )}
          </div>
          <div>
            {reading && !draft ? (
              <div class="flex h-full min-h-48 flex-col items-center justify-center gap-3 text-center">
                <Spinner class="h-8 w-8 text-brand-600" />
                <p class="font-medium">Reading the receipt…</p>
                <p class="muted text-sm">Usually a few seconds. You can close this; it’ll wait in the review queue.</p>
                <button class="btn text-sm" onClick={() => setDraft(toDraft(receipt))}>
                  Fill in by hand
                </button>
              </div>
            ) : (
              draft && <ReceiptEditor receipt={receipt} draft={draft} onChange={setDraft} />
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
