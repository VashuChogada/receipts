// The form for one receipt's fields: used by the review modal and the
// receipt page. Typed tags (HSA, Donation, Warranty) add their own fields.

import { useEffect, useMemo, useState } from 'preact/hooks';
import { api, type Donation, type Hsa, type LineItem, type Receipt, type Warranty } from '../api';
import { fmtMoney } from '../lib/format';
import { useStore } from '../store';
import { Field, Icon, TagChip } from './ui';

export interface Draft {
  merchant: string;
  txn_date: string;
  txn_time: string;
  total: string;
  subtotal: string;
  tax: string;
  payment_method: string;
  card_last4: string;
  category: string;
  notes: string;
  tags: string[];
  hsa: Hsa;
  donation: Donation;
  warranty: Warranty;
  line_items: LineItem[];
  remember_category: boolean;
}

const s = (v: unknown) => (v === null || v === undefined ? '' : String(v));
const money = (v: number | null | undefined) => (v === null || v === undefined ? '' : v.toFixed(2));

export function toDraft(r: Receipt): Draft {
  return {
    merchant: s(r.merchant),
    txn_date: s(r.txn_date),
    txn_time: s(r.txn_time),
    total: money(r.total),
    subtotal: money(r.subtotal),
    tax: money(r.tax),
    payment_method: s(r.payment_method),
    card_last4: s(r.card_last4),
    category: s(r.category),
    notes: s(r.notes),
    tags: [...r.tags],
    hsa: { ...(r.hsa ?? {}) },
    donation: { donation_type: 'cash', ...(r.donation ?? {}) },
    warranty: { ...(r.warranty ?? {}) },
    line_items: r.line_items.map((i) => ({ ...i })),
    remember_category: false,
  };
}

const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(/[$,]/g, '')));

/** The PATCH body: only what differs from the receipt as loaded. */
export function toPatch(d: Draft, r: Receipt, kinds: Set<string>): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  const scalar: [keyof Draft, unknown, unknown][] = [
    ['merchant', d.merchant.trim() || null, r.merchant],
    ['txn_date', d.txn_date || null, r.txn_date],
    ['txn_time', d.txn_time || null, r.txn_time],
    ['total', num(d.total), r.total],
    ['subtotal', num(d.subtotal), r.subtotal],
    ['tax', num(d.tax), r.tax],
    ['payment_method', d.payment_method.trim() || null, r.payment_method],
    ['card_last4', d.card_last4.trim() || null, r.card_last4],
    ['category', d.category || null, r.category],
    ['notes', d.notes.trim() || null, r.notes],
  ];
  for (const [k, v, old] of scalar) if (v !== old) patch[k] = v;
  if (JSON.stringify(d.tags) !== JSON.stringify(r.tags)) patch.tags = d.tags;
  if (kinds.has('hsa')) patch.hsa = d.hsa;
  if (kinds.has('donation')) patch.donation = d.donation;
  if (kinds.has('warranty')) patch.warranty = d.warranty;
  if (JSON.stringify(d.line_items) !== JSON.stringify(r.line_items)) patch.line_items = d.line_items;
  if (d.remember_category) patch.remember_category = true;
  return patch;
}

const PAYMENTS = ['Visa', 'Mastercard', 'Amex', 'Discover', 'Debit', 'Cash', 'Apple Pay', 'Google Pay', 'Check'];

export function ReceiptEditor(props: { receipt: Receipt; draft: Draft; onChange: (d: Draft) => void }) {
  const { categories, tags, people, merchants } = useStore();
  const d = props.draft;
  const r = props.receipt;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => props.onChange({ ...d, [k]: v });
  const [newTag, setNewTag] = useState('');
  const [showItems, setShowItems] = useState(false);

  const kinds = useMemo(
    () => new Set(d.tags.map((t) => tags.find((x) => x.name.toLowerCase() === t.toLowerCase())?.kind).filter(Boolean) as string[]),
    [d.tags, tags],
  );
  const suggestions = r.suggested_tags.filter((t) => !d.tags.includes(t));
  const sumCheck =
    num(d.subtotal) !== null && num(d.tax) !== null && num(d.total) !== null
      ? Math.abs((num(d.subtotal)! + num(d.tax)!) - num(d.total)!) < 0.015
      : null;

  const toggleTag = (name: string) =>
    set('tags', d.tags.includes(name) ? d.tags.filter((t) => t !== name) : [...d.tags, name].sort((a, b) => a.localeCompare(b)));

  const field = (k: keyof Draft) => ({
    value: d[k] as string,
    onInput: (e: Event) => set(k, (e.target as HTMLInputElement).value as never),
  });

  return (
    <div class="space-y-4">
      {suggestions.length > 0 && (
        <div class="flex flex-wrap items-center gap-2 rounded-xl bg-brand-50 px-3 py-2 text-sm text-brand-800 dark:bg-brand-800/20 dark:text-brand-100">
          <Icon name="sparkle" size={16} /> Looks like
          {suggestions.map((t) => (
            <button key={t} class="chip border-brand-600 bg-white font-semibold dark:bg-neutral-900" onClick={() => toggleTag(t)}>
              + {t}
            </button>
          ))}
        </div>
      )}

      <Field label="Merchant">
        <input class="input" list="merchant-list" {...field('merchant')} placeholder={r.merchant_raw ?? 'Store name'} />
        <datalist id="merchant-list">{merchants.map((m) => <option key={m} value={m} />)}</datalist>
      </Field>

      <div class="grid grid-cols-2 gap-3">
        <Field label="Date">
          <input class="input" type="date" {...field('txn_date')} />
        </Field>
        <Field label="Time">
          <input class="input" type="time" {...field('txn_time')} />
        </Field>
      </div>

      <div class="grid grid-cols-3 gap-3">
        <Field label="Total">
          <input class="input text-lg font-semibold" inputMode="decimal" {...field('total')} placeholder="0.00" />
        </Field>
        <Field label="Subtotal">
          <input class="input" inputMode="decimal" {...field('subtotal')} />
        </Field>
        <Field label="Tax">
          <input class="input" inputMode="decimal" {...field('tax')} />
        </Field>
      </div>
      {sumCheck === false && (
        <p class="-mt-2 flex items-center gap-1 text-xs text-amber-600">
          <Icon name="alert" size={14} /> Subtotal + tax is {fmtMoney(num(d.subtotal)! + num(d.tax)!)}, not the total.
        </p>
      )}

      <Field label="Category">
        <div class="flex flex-wrap gap-1.5">
          {categories.map((c) => {
            const on = d.category.toLowerCase() === c.name.toLowerCase();
            return (
              <button
                key={c.name}
                type="button"
                class={`pill gap-1.5 ${on ? 'pill-on' : ''}`}
                aria-pressed={on}
                onClick={() => set('category', c.name)}
              >
                <span class="h-2 w-2 rounded-full" style={{ background: c.color }} />
                {c.name}
              </button>
            );
          })}
        </div>
      </Field>
      {d.merchant && d.category && (
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={d.remember_category} onChange={(e) => set('remember_category', (e.target as HTMLInputElement).checked)} />
          Always file <b>{d.merchant}</b> under <b>{d.category}</b>
        </label>
      )}

      <Field label="Tags">
        <div class="flex flex-wrap items-center gap-1.5">
          {tags.map((t) => {
            const on = d.tags.some((x) => x.toLowerCase() === t.name.toLowerCase());
            return (
              <button
                key={t.name}
                type="button"
                class={`pill gap-1.5 ${on ? 'pill-on' : ''}`}
                aria-pressed={on}
                onClick={() => toggleTag(t.name)}
              >
                {t.name}
              </button>
            );
          })}
          {d.tags.filter((t) => !tags.some((x) => x.name.toLowerCase() === t.toLowerCase())).map((t) => (
            <TagChip key={t} name={t} onRemove={() => toggleTag(t)} />
          ))}
          <form
            class="inline-flex"
            onSubmit={(e) => {
              e.preventDefault();
              if (newTag.trim()) toggleTag(newTag.trim());
              setNewTag('');
            }}
          >
            <input class="input min-h-0 w-24 py-1 text-sm" placeholder="+ tag" value={newTag} onInput={(e) => setNewTag((e.target as HTMLInputElement).value)} />
          </form>
        </div>
      </Field>

      {kinds.has('hsa') && (
        <fieldset class="space-y-3 rounded-xl border border-neutral-200 p-3 dark:border-neutral-800">
          <legend class="px-1 text-sm font-semibold">HSA</legend>
          <div class="grid grid-cols-2 gap-3">
            <Field label="Patient">
              <input class="input" list="people-list" value={s(d.hsa.patient)} onInput={(e) => set('hsa', { ...d.hsa, patient: (e.target as HTMLInputElement).value })} />
              <datalist id="people-list">{people.map((p) => <option key={p.id} value={p.display_name} />)}</datalist>
            </Field>
            <Field label="Provider">
              <input class="input" value={s(d.hsa.provider)} onInput={(e) => set('hsa', { ...d.hsa, provider: (e.target as HTMLInputElement).value })} />
            </Field>
            <Field label="Eligible amount" hint="Blank = the total">
              <input class="input" inputMode="decimal" value={s(d.hsa.eligible_amount)} onInput={(e) => set('hsa', { ...d.hsa, eligible_amount: num((e.target as HTMLInputElement).value) })} />
            </Field>
            <Field label="Claim ref">
              <input class="input" value={s(d.hsa.claim_ref)} onInput={(e) => set('hsa', { ...d.hsa, claim_ref: (e.target as HTMLInputElement).value })} />
            </Field>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <label class="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!d.hsa.reimbursed}
                onChange={(e) => {
                  const on = (e.target as HTMLInputElement).checked;
                  set('hsa', { ...d.hsa, reimbursed: on, reimbursed_date: on ? d.hsa.reimbursed_date || new Date().toISOString().slice(0, 10) : null });
                }}
              />
              Reimbursed
            </label>
            {d.hsa.reimbursed && (
              <input class="input w-auto" type="date" value={s(d.hsa.reimbursed_date)} onInput={(e) => set('hsa', { ...d.hsa, reimbursed_date: (e.target as HTMLInputElement).value })} />
            )}
          </div>
        </fieldset>
      )}

      {kinds.has('donation') && (
        <fieldset class="space-y-3 rounded-xl border border-neutral-200 p-3 dark:border-neutral-800">
          <legend class="px-1 text-sm font-semibold">Donation</legend>
          <div class="grid grid-cols-2 gap-3">
            <Field label="Organization" class="col-span-2">
              <input class="input" value={s(d.donation.organization)} placeholder={d.merchant} onInput={(e) => set('donation', { ...d.donation, organization: (e.target as HTMLInputElement).value })} />
            </Field>
            <Field label="EIN">
              <input class="input" value={s(d.donation.ein)} placeholder="12-3456789" onInput={(e) => set('donation', { ...d.donation, ein: (e.target as HTMLInputElement).value })} />
            </Field>
            <Field label="Type">
              <select class="input" value={d.donation.donation_type ?? 'cash'} onChange={(e) => set('donation', { ...d.donation, donation_type: (e.target as HTMLSelectElement).value as 'cash' | 'noncash' })}>
                <option value="cash">Cash / card</option>
                <option value="noncash">Goods (non-cash)</option>
              </select>
            </Field>
            <Field label="Deductible amount" hint="Blank = the total">
              <input class="input" inputMode="decimal" value={s(d.donation.deductible_amount)} onInput={(e) => set('donation', { ...d.donation, deductible_amount: num((e.target as HTMLInputElement).value) })} />
            </Field>
            {d.donation.donation_type === 'noncash' && (
              <Field label="Items donated" class="col-span-2">
                <input class="input" value={s(d.donation.items_description)} onInput={(e) => set('donation', { ...d.donation, items_description: (e.target as HTMLInputElement).value })} />
              </Field>
            )}
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!d.donation.acknowledgment} onChange={(e) => set('donation', { ...d.donation, acknowledgment: (e.target as HTMLInputElement).checked })} />
            I have the charity’s written acknowledgment
          </label>
          {(num(s(d.donation.deductible_amount)) ?? num(d.total) ?? 0) >= 250 && !d.donation.acknowledgment && (
            <p class="flex gap-1 text-xs text-amber-700 dark:text-amber-400">
              <Icon name="alert" size={14} class="mt-0.5 shrink-0" />
              Gifts of $250 or more need a written acknowledgment from the charity to deduct. Attach it on the receipt page.
            </p>
          )}
        </fieldset>
      )}

      {kinds.has('warranty') && (
        <fieldset class="space-y-3 rounded-xl border border-neutral-200 p-3 dark:border-neutral-800">
          <legend class="px-1 text-sm font-semibold">Warranty</legend>
          <div class="grid grid-cols-2 gap-3">
            <Field label="Product" class="col-span-2">
              <input class="input" value={s(d.warranty.product)} onInput={(e) => set('warranty', { ...d.warranty, product: (e.target as HTMLInputElement).value })} />
            </Field>
            <Field label="Serial">
              <input class="input" value={s(d.warranty.serial)} onInput={(e) => set('warranty', { ...d.warranty, serial: (e.target as HTMLInputElement).value })} />
            </Field>
            <Field label="Expires">
              <input class="input" type="date" value={s(d.warranty.expires_on)} onInput={(e) => set('warranty', { ...d.warranty, expires_on: (e.target as HTMLInputElement).value })} />
            </Field>
          </div>
        </fieldset>
      )}

      <div class="grid grid-cols-2 gap-3">
        <Field label="Paid with">
          <input class="input" list="payment-list" {...field('payment_method')} />
          <datalist id="payment-list">{PAYMENTS.map((p) => <option key={p} value={p} />)}</datalist>
        </Field>
        <Field label="Card last 4">
          <input class="input" inputMode="numeric" maxLength={4} {...field('card_last4')} />
        </Field>
      </div>

      <Field label="Notes">
        <textarea class="input min-h-16" rows={2} {...field('notes')} />
      </Field>

      <div>
        <button type="button" class="flex w-full items-center justify-between text-sm font-medium" onClick={() => setShowItems(!showItems)}>
          <span>Line items ({d.line_items.length})</span>
          <Icon name="chevron" size={16} class={`transition ${showItems ? 'rotate-90' : ''}`} />
        </button>
        {showItems && (
          <div class="mt-2 space-y-1.5">
            {d.line_items.map((it, i) => (
              <div key={i} class="flex gap-2">
                <input
                  class="input min-h-9 flex-1 py-1 text-sm"
                  value={it.description}
                  onInput={(e) => set('line_items', d.line_items.map((x, j) => (j === i ? { ...x, description: (e.target as HTMLInputElement).value } : x)))}
                />
                <input
                  class="input min-h-9 w-24 py-1 text-right text-sm"
                  inputMode="decimal"
                  value={s(it.amount)}
                  onInput={(e) => set('line_items', d.line_items.map((x, j) => (j === i ? { ...x, amount: num((e.target as HTMLInputElement).value) } : x)))}
                />
                <button class="btn btn-ghost px-2" onClick={() => set('line_items', d.line_items.filter((_, j) => j !== i))} aria-label="Remove item">
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))}
            <button class="btn btn-ghost text-sm" onClick={() => set('line_items', [...d.line_items, { description: '', amount: null }])}>
              <Icon name="plus" size={16} /> Add item
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function kindsOf(draft: Draft, tags: { name: string; kind: string }[]): Set<string> {
  return new Set(draft.tags.map((t) => tags.find((x) => x.name.toLowerCase() === t.toLowerCase())?.kind).filter((k): k is string => !!k && k !== 'plain'));
}

/** Load a receipt and keep polling while the server is still reading it. */
export function useReceipt(id: string | null) {
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const r = await api.get<Receipt>(`/api/receipts/${id}`);
        if (cancelled) return;
        setReceipt(r);
        setError(null);
        if (r.status === 'queued' || r.status === 'processing') timer = setTimeout(load, 1500);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    };
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, tick]);
  return { receipt, setReceipt, error, reload: () => setTick((t) => t + 1) };
}
