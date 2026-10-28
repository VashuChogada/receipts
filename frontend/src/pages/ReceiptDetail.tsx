import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation, useRoute } from 'preact-iso';
import { api, previewUrl, type Receipt } from '../api';
import { ReceiptEditor, kindsOf, toDraft, toPatch, useReceipt, type Draft } from '../components/ReceiptEditor';
import { CategoryChip, Icon, Spinner, TagChip } from '../components/ui';
import { fmtDate, fmtDateTime, fmtMoney, statusLabel } from '../lib/format';
import { useStore } from '../store';

export function ReceiptDetail() {
  const { params } = useRoute();
  const { route } = useLocation();
  const store = useStore();
  const { receipt, setReceipt, error, reload } = useReceipt(params.id);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [fullImage, setFullImage] = useState(false);
  const attachRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (receipt && !editing) setDraft(toDraft(receipt));
  }, [receipt]);

  if (error) return <p class="p-4 text-red-600">{error}</p>;
  if (!receipt || !draft) return <div class="space-y-4"><div class="h-8 w-1/2 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" /><div class="card h-72 animate-pulse" /></div>;

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.patch<Receipt>(`/api/receipts/${receipt.id}`, toPatch(draft, receipt, kindsOf(draft, store.tags)));
      setReceipt(updated);
      setEditing(false);
      store.bump();
      store.toast('Saved');
    } catch (e) {
      store.toast((e as Error).message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const attach = async (files: FileList | null) => {
    if (!files?.length) return;
    const label = prompt('Label for this attachment (e.g. "Acknowledgment letter", "EOB")', '') ?? '';
    const form = new FormData();
    form.append('file', files[0]);
    form.append('label', label);
    try {
      setReceipt(await api.post<Receipt>(`/api/receipts/${receipt.id}/attachments`, form));
      store.toast('Attached');
    } catch (e) {
      store.toast((e as Error).message, 'error');
    }
  };

  const reprocess = async () => {
    await api.post(`/api/receipts/${receipt.id}/reprocess`);
    store.toast('Reading it again…');
    setTimeout(reload, 500);
  };

  const remove = async () => {
    if (!confirm('Delete this receipt? Its files move to the trash folder.')) return;
    await api.del(`/api/receipts/${receipt.id}`);
    store.bump();
    route('/receipts', true);
  };

  const isPdf = receipt.mime === 'application/pdf';

  return (
    <div class="space-y-4">
      <div class="flex items-center gap-2">
        <button class="btn btn-ghost -ml-2 px-2" onClick={() => history.back()} aria-label="Back">
          <Icon name="back" />
        </button>
        <div class="min-w-0 flex-1">
          <h1 class="page-title truncate">{receipt.merchant ?? 'Unknown merchant'}</h1>
          <p class="muted text-sm">
            {fmtDate(receipt.txn_date)} {receipt.txn_time && `· ${receipt.txn_time}`} · {statusLabel[receipt.status]}
          </p>
        </div>
        <p class="text-xl font-semibold tabular-nums">{fmtMoney(receipt.total)}</p>
      </div>

      <div class="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div class="space-y-2">
          <button class="block max-h-96 w-full overflow-hidden rounded-xl border border-neutral-200 bg-neutral-100 md:max-h-none dark:border-neutral-800 dark:bg-neutral-800" onClick={() => setFullImage(true)} aria-label="Show the whole scan">
            <img src={previewUrl(receipt, 1200)} alt="Receipt scan" class="w-full object-cover object-top" />
          </button>
          <div class="flex flex-wrap gap-2">
            <a class="btn text-sm" href={`/api/receipts/${receipt.id}/file`} target="_blank" rel="noopener">
              <Icon name={isPdf ? 'file' : 'image'} size={16} /> Original
            </a>
            <button class="btn text-sm" onClick={reprocess}>
              <Icon name="refresh" size={16} /> Read again
            </button>
            <button class="btn btn-danger text-sm" onClick={remove}>
              <Icon name="trash" size={16} /> Delete
            </button>
          </div>
          <p class="muted text-xs break-all">{receipt.file_path}</p>
        </div>

        <div class="space-y-4">
          {receipt.needs_acknowledgment && (
            <p class="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              This gift is $250 or more: attach the charity’s written acknowledgment (or tick that you have it) to keep the deduction.
            </p>
          )}
          {editing ? (
            <div class="card">
              <ReceiptEditor receipt={receipt} draft={draft} onChange={setDraft} />
              <div class="mt-4 flex justify-end gap-2">
                <button class="btn" onClick={() => { setEditing(false); setDraft(toDraft(receipt)); }}>
                  Cancel
                </button>
                <button class="btn btn-primary" onClick={save} disabled={saving}>
                  {saving && <Spinner />} Save
                </button>
              </div>
            </div>
          ) : (
            <div class="card space-y-3">
              <div class="flex flex-wrap items-center gap-1.5">
                <CategoryChip name={receipt.category} />
                {receipt.tags.map((t) => <TagChip key={t} name={t} />)}
                <div class="flex-1" />
                <button class="btn min-h-8 text-sm" onClick={() => (receipt.status === 'confirmed' ? setEditing(true) : store.openReview(receipt.id))}>
                  Edit
                </button>
              </div>
              <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <Row k="Subtotal" v={fmtMoney(receipt.subtotal)} />
                <Row k="Tax" v={fmtMoney(receipt.tax)} />
                <Row k="Paid with" v={[receipt.payment_method, receipt.card_last4 && `••${receipt.card_last4}`].filter(Boolean).join(' ') || '—'} />
                <Row k="Added by" v={receipt.created_by ?? '—'} />
                {receipt.hsa && receipt.kinds.includes('hsa') && (
                  <>
                    <Row k="Patient" v={receipt.hsa.patient ?? '—'} />
                    <Row k="Reimbursed" v={receipt.hsa.reimbursed ? fmtDate(receipt.hsa.reimbursed_date) : 'Not yet'} />
                  </>
                )}
                {receipt.donation && receipt.kinds.includes('donation') && (
                  <>
                    <Row k="Organization" v={receipt.donation.organization ?? receipt.merchant ?? '—'} />
                    <Row k="EIN" v={receipt.donation.ein ?? '—'} />
                    <Row k="Deductible" v={fmtMoney(receipt.donation.deductible_amount ?? receipt.total)} />
                    <Row k="Type" v={receipt.donation.donation_type === 'noncash' ? 'Non-cash' : 'Cash'} />
                  </>
                )}
                {receipt.warranty && receipt.kinds.includes('warranty') && (
                  <>
                    <Row k="Product" v={receipt.warranty.product ?? '—'} />
                    <Row k="Warranty ends" v={fmtDate(receipt.warranty.expires_on)} />
                  </>
                )}
              </dl>
              {receipt.notes && <p class="text-sm whitespace-pre-wrap">{receipt.notes}</p>}
              {receipt.line_items.length > 0 && (
                <details>
                  <summary class="cursor-pointer text-sm font-medium">{receipt.line_items.length} line items</summary>
                  <ul class="mt-2 space-y-1 text-sm">
                    {receipt.line_items.map((i, n) => (
                      <li key={n} class="flex justify-between gap-2">
                        <span class="truncate">{i.description}</span>
                        <span class="tabular-nums">{fmtMoney(i.amount)}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          <div class="card space-y-2">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold">Attachments</h2>
              <button class="btn min-h-8 text-sm" onClick={() => attachRef.current?.click()}>
                <Icon name="paperclip" size={16} /> Attach
              </button>
              <input ref={attachRef} type="file" accept="image/*,application/pdf" class="hidden" onChange={(e) => attach((e.target as HTMLInputElement).files)} />
            </div>
            {receipt.attachments.length === 0 && <p class="muted text-sm">Letters, EOBs, warranty cards…</p>}
            {receipt.attachments.map((a) => (
              <div key={a.id} class="flex items-center gap-2 text-sm">
                <Icon name="file" size={16} />
                <a class="flex-1 truncate underline-offset-2 hover:underline" href={`/api/receipts/${receipt.id}/attachments/${a.id}`} target="_blank" rel="noopener">
                  {a.label || a.original_name || 'Attachment'}
                </a>
                <button
                  class="btn btn-ghost min-h-8 px-2"
                  aria-label="Remove attachment"
                  onClick={async () => {
                    if (confirm('Remove this attachment?')) setReceipt(await api.del<Receipt>(`/api/receipts/${receipt.id}/attachments/${a.id}`));
                  }}
                >
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))}
          </div>

          {receipt.raw_text && (
            <details class="card">
              <summary class="cursor-pointer text-sm font-semibold">Text read from the receipt</summary>
              <pre class="mt-2 max-h-80 overflow-auto text-xs whitespace-pre-wrap text-neutral-600 dark:text-neutral-300">{receipt.raw_text}</pre>
            </details>
          )}

          {receipt.history.length > 0 && (
            <details class="card">
              <summary class="cursor-pointer text-sm font-semibold">History ({receipt.history.length})</summary>
              <ul class="mt-2 space-y-2 text-xs">
                {[...receipt.history].reverse().map((h, i) => (
                  <li key={i}>
                    <span class="muted">{fmtDateTime(h.at)} · {h.by ?? 'system'}</span>
                    <div>
                      {Object.entries(h.changes).map(([k, [a, b]]) => (
                        <div key={k}>
                          <b>{k}</b>: {short(a)} → {short(b)}
                        </div>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>

      {fullImage && (
        <div class="fixed inset-0 z-50 overflow-auto bg-black" onClick={() => setFullImage(false)}>
          <img src={isPdf ? previewUrl(receipt, 1200) : `/api/receipts/${receipt.id}/file`} alt="Receipt full size" class="mx-auto max-w-none sm:max-w-full" />
        </div>
      )}
    </div>
  );
}

function Row(props: { k: string; v: string }) {
  return (
    <div>
      <dt class="muted text-xs">{props.k}</dt>
      <dd>{props.v}</dd>
    </div>
  );
}

function short(v: unknown): string {
  if (v === null || v === undefined || v === '') return '∅';
  if (typeof v === 'object') return Array.isArray(v) ? v.join(', ') || '∅' : '…';
  return String(v);
}
