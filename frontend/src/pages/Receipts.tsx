// Search and browse. The box takes plain English ("costco over $50 last
// month"); the server answers with the filters it understood, shown as chips.
// Removing a chip turns the query into explicit filters minus that one.

import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, qs, type ReceiptSummary, type SearchResult } from '../api';
import { MonthGroups, ReceiptGrid, RowList } from '../components/ReceiptList';
import { Empty, Field, Icon, Modal, SkeletonRows, Spinner } from '../components/ui';
import { debounce, fmtMoney } from '../lib/format';
import { useStore } from '../store';

const FILTER_KEYS = ['date_from', 'date_to', 'min_total', 'max_total', 'merchant', 'category', 'tag', 'payment_method', 'card_last4', 'status', 'created_by', 'reimbursed', 'sort'] as const;
const PAGE = 50;

const EXAMPLES = ['costco over $50 last month', 'dining in march', 'unreimbursed hsa', 'donations 2025', 'coffee', 'visa this year'];

type Params = Record<string, string | string[]>;

function readParams(search: string): Params {
  const sp = new URLSearchParams(search);
  const out: Params = {};
  for (const [k, v] of sp) {
    if (k === 'tag') out.tag = [...((out.tag as string[]) ?? []), v];
    else out[k] = v;
  }
  return out;
}

/** "2026" when the date filter is exactly that whole year, else null. */
function yearOf(p: Params): string | null {
  const from = String(p.date_from ?? '');
  return from.endsWith('-01-01') && p.date_to === `${from.slice(0, 4)}-12-31` ? from.slice(0, 4) : null;
}

export function Receipts() {
  const store = useStore();
  const loc = useLocation();
  const params = useMemo(() => readParams(loc.url.split('?')[1] ?? ''), [loc.url]);
  const [text, setText] = useState((params.q as string) ?? '');
  const [result, setResult] = useState<SearchResult | null>(null);
  const [items, setItems] = useState<ReceiptSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [grid, setGrid] = useState(() => localStorage.getItem('receipts.grid') === '1');
  const [showFilters, setShowFilters] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [years, setYears] = useState<string[]>([]);
  const seq = useRef(0);

  useEffect(() => {
    api.get<{ years: string[] }>('/api/reports/overview').then((o) => setYears(o.years)).catch(() => {});
  }, [store.version]);

  const go = (next: Params) => loc.route(`/receipts${qs(next)}`, true);
  const pushText = useMemo(() => debounce((q: string) => go({ ...params, q }), 350), [params]);

  useEffect(() => setText((params.q as string) ?? ''), [params.q]);

  const load = async (offset: number) => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const r = await api.get<SearchResult>(`/api/receipts${qs({ ...params, limit: PAGE, offset })}`);
      if (mine !== seq.current) return;
      setResult(r);
      setItems((prev) => (offset ? [...prev, ...r.items] : r.items));
    } catch (e) {
      store.toast((e as Error).message, 'error');
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  };

  useEffect(() => {
    load(0);
  }, [loc.url, store.version]);

  const removeChip = (key: string) => {
    if (!result) return;
    // Pin what the query meant as explicit filters, drop the chip's, keep the free text.
    const f = result.query.filters as Record<string, unknown>;
    const next: Params = {};
    for (const k of FILTER_KEYS) {
      const v = k === 'tag' ? (f.tags as string[]) : f[k];
      if (v === null || v === undefined || (Array.isArray(v) && !v.length)) continue;
      next[k] = Array.isArray(v) ? v.map(String) : String(v);
    }
    if (params.sort) next.sort = params.sort;
    const drop: Record<string, string[]> = {
      date: ['date_from', 'date_to'],
      amount: ['min_total', 'max_total'],
      tag: ['tag'],
    };
    for (const k of drop[key] ?? [key]) delete next[k];
    if (key === 'reimbursed') next.tag = ((next.tag as string[]) ?? []).filter((t) => t !== 'HSA');
    if (result.query.text) next.q = result.query.text;
    go(next);
  };

  const explicitChips = FILTER_KEYS.filter((k) => k !== 'sort' && params[k] && !(k === 'tag' || ((k === 'date_from' || k === 'date_to') && yearOf(params)))).map((k) => ({
    key: k,
    label: `${k.replace('_', ' ')}: ${Array.isArray(params[k]) ? (params[k] as string[]).join(', ') : params[k]}`,
  }));

  const open = (r: ReceiptSummary) => {
    if (r.status === 'confirmed') loc.route(`/receipts/${r.id}`);
    else store.openReview(r.id, items.filter((x) => x.status !== 'confirmed').map((x) => x.id));
  };

  const exportQuery = qs({ ...params });

  // Quick filters: a year, and the tags that matter at tax time.
  const activeYear = yearOf(params);
  const setYear = (y: string | null) => {
    const next = { ...params };
    delete next.date_from;
    delete next.date_to;
    go(y ? { ...next, date_from: `${y}-01-01`, date_to: `${y}-12-31` } : next);
  };
  const activeTags = (params.tag as string[]) ?? [];
  const toggleTag = (name: string) =>
    go({ ...params, tag: activeTags.includes(name) ? activeTags.filter((x) => x !== name) : [...activeTags, name] });
  const KIND_ORDER = ['hsa', 'donation', 'warranty'];
  const quickTags = store.tags.filter((t) => t.kind !== 'plain').sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
  const grouped = !result?.query.text && (!params.sort || params.sort === 'date');

  return (
    <div class="space-y-3">
      <div class="sticky top-0 z-10 -mx-4 bg-neutral-50/95 px-4 pt-[max(env(safe-area-inset-top),0.25rem)] pb-2 md:top-[3.25rem] dark:bg-neutral-950/95">
        <div class="relative">
          <Icon name="search" size={18} class="absolute top-1/2 left-3 -translate-y-1/2 text-neutral-400" />
          <input
            class="input pr-22 pl-10"
            type="search"
            placeholder="Search: “costco over $50”"
            value={text}
            onInput={(e) => {
              const v = (e.target as HTMLInputElement).value;
              setText(v);
              pushText(v);
            }}
            enterKeyHint="search"
          />
          <div class="absolute top-1/2 right-1 flex -translate-y-1/2">
            <button class="btn btn-ghost min-h-8 px-2" onClick={() => setShowFilters(true)} aria-label="Filters">
              <Icon name="filter" size={18} />
            </button>
            <button
              class="btn btn-ghost min-h-8 px-2"
              onClick={() => {
                setGrid(!grid);
                localStorage.setItem('receipts.grid', grid ? '0' : '1');
              }}
              aria-label={grid ? 'List view' : 'Gallery view'}
            >
              <Icon name={grid ? 'list' : 'grid'} size={18} />
            </button>
          </div>
        </div>

        <div class="no-scrollbar -mx-4 mt-2 flex gap-2 overflow-x-auto px-4">
          <button class={`pill ${!activeYear ? 'pill-on' : ''}`} onClick={() => setYear(null)}>
            All years
          </button>
          {years.map((y) => (
            <button key={y} class={`pill ${activeYear === y ? 'pill-on' : ''}`} onClick={() => setYear(activeYear === y ? null : y)}>
              {y}
            </button>
          ))}
          <span class="mx-1 w-px shrink-0 bg-neutral-200 dark:bg-neutral-800" />
          {quickTags.map((t) => (
            <button key={t.name} class={`pill ${activeTags.includes(t.name) ? 'pill-on' : ''}`} onClick={() => toggleTag(t.name)}>
              {t.name}
            </button>
          ))}
        </div>

        {(result?.query.chips.length || explicitChips.length) ? (
          <div class="mt-2 flex flex-wrap gap-1.5">
            {result?.query.chips.map((c) => (
              <button key={c.key + c.label} class="chip border-neutral-300 bg-white py-1 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200" onClick={() => removeChip(c.key)} aria-label={`Remove filter ${c.label}`}>
                {c.label} <Icon name="x" size={12} />
              </button>
            ))}
            {explicitChips.map((c) => (
              <button
                key={c.key}
                class="chip border-neutral-300 text-neutral-600 dark:text-neutral-300"
                onClick={() => {
                  const next = { ...params };
                  delete next[c.key];
                  go(next);
                }}
              >
                {c.label} <Icon name="x" size={12} />
              </button>
            ))}
            {result?.query.text && <span class="chip border-dashed border-neutral-300 text-neutral-500">“{result.query.text}”</span>}
          </div>
        ) : null}
      </div>

      {result && (
        <div class="flex items-center justify-between text-sm">
          <span class="muted">
            {result.total} {result.total === 1 ? 'receipt' : 'receipts'} · <b class="font-medium text-neutral-800 dark:text-neutral-100">{fmtMoney(result.summary.total)}</b>
          </span>
          <button class="btn btn-ghost min-h-8 px-2 text-sm" onClick={() => setShowExport(true)}>
            <Icon name="download" size={16} /> Export
          </button>
        </div>
      )}

      {!result && loading && <SkeletonRows n={6} />}

      {result && items.length === 0 && !loading && (
        <Empty title="Nothing matches" icon="search">
          <p>Try one of these:</p>
          <div class="mt-2 flex flex-wrap justify-center gap-1.5">
            {EXAMPLES.map((ex) => (
              <button key={ex} class="chip border-neutral-300" onClick={() => go({ q: ex })}>
                {ex}
              </button>
            ))}
          </div>
        </Empty>
      )}

      {items.length > 0 &&
        (grid ? (
          <ReceiptGrid items={items} onOpen={open} />
        ) : grouped ? (
          <MonthGroups items={items} onOpen={open} />
        ) : (
          <RowList items={items} onOpen={open} />
        ))}

      {result && items.length < result.total && (
        <button class="btn w-full" onClick={() => load(items.length)} disabled={loading}>
          {loading ? <Spinner /> : `Load more (${result.total - items.length})`}
        </button>
      )}

      <FilterSheet open={showFilters} onClose={() => setShowFilters(false)} params={params} onApply={(p) => go(p)} />

      <Modal open={showExport} onClose={() => setShowExport(false)} title="Export these receipts">
        <div class="space-y-2 p-4">
          <p class="muted text-sm">Exactly what the list shows: {result?.total ?? 0} receipts.</p>
          <a class="btn w-full justify-start" href={`/api/export.csv${exportQuery}`} download>
            <Icon name="file" /> CSV for a spreadsheet
          </a>
          <a class="btn w-full justify-start" href={`/api/export.json${exportQuery}`} download>
            <Icon name="file" /> JSON with every field
          </a>
          <a class="btn w-full justify-start" href={`/api/export.zip${qs({ ...params, name: 'receipts' })}`} download>
            <Icon name="download" /> ZIP: CSV plus every image and PDF
          </a>
        </div>
      </Modal>
    </div>
  );
}

function FilterSheet(props: { open: boolean; onClose: () => void; params: Params; onApply: (p: Params) => void }) {
  const { categories, tags, people } = useStore();
  const [p, setP] = useState<Params>(props.params);
  useEffect(() => setP(props.params), [props.params, props.open]);
  const val = (k: string) => (p[k] as string) ?? '';
  const set = (k: string, v: string) => setP({ ...p, [k]: v });

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title="Filters"
      footer={
        <div class="flex gap-2">
          <button class="btn flex-1" onClick={() => setP({ q: (p.q as string) ?? '' })}>
            Clear
          </button>
          <button
            class="btn btn-primary flex-1"
            onClick={() => {
              props.onApply(Object.fromEntries(Object.entries(p).filter(([, v]) => v !== '' && !(Array.isArray(v) && !v.length))));
              props.onClose();
            }}
          >
            Apply
          </button>
        </div>
      }
    >
      <div class="space-y-4 p-4">
        <div class="grid grid-cols-2 gap-3">
          <Field label="From">
            <input class="input" type="date" value={val('date_from')} onInput={(e) => set('date_from', (e.target as HTMLInputElement).value)} />
          </Field>
          <Field label="To">
            <input class="input" type="date" value={val('date_to')} onInput={(e) => set('date_to', (e.target as HTMLInputElement).value)} />
          </Field>
          <Field label="Min total">
            <input class="input" inputMode="decimal" value={val('min_total')} onInput={(e) => set('min_total', (e.target as HTMLInputElement).value)} />
          </Field>
          <Field label="Max total">
            <input class="input" inputMode="decimal" value={val('max_total')} onInput={(e) => set('max_total', (e.target as HTMLInputElement).value)} />
          </Field>
        </div>
        <Field label="Category">
          <select class="input" value={val('category')} onChange={(e) => set('category', (e.target as HTMLSelectElement).value)}>
            <option value="">Any</option>
            {categories.map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Tags">
          <div class="flex flex-wrap gap-1.5">
            {tags.map((t) => {
              const on = ((p.tag as string[]) ?? []).includes(t.name);
              return (
                <button
                  key={t.name}
                  class={`pill gap-1.5 ${on ? 'pill-on' : ''}`}
                  aria-pressed={on}
                  onClick={() => {
                    const cur = (p.tag as string[]) ?? [];
                    setP({ ...p, tag: on ? cur.filter((x) => x !== t.name) : [...cur, t.name] });
                  }}
                >
                  {t.name}
                </button>
              );
            })}
          </div>
        </Field>
        <div class="grid grid-cols-2 gap-3">
          <Field label="Status">
            <select class="input" value={val('status')} onChange={(e) => set('status', (e.target as HTMLSelectElement).value)}>
              <option value="">Any</option>
              <option value="confirmed">Filed</option>
              <option value="review">To review</option>
              <option value="failed">Couldn’t read</option>
            </select>
          </Field>
          <Field label="Added by">
            <select class="input" value={val('created_by')} onChange={(e) => set('created_by', (e.target as HTMLSelectElement).value)}>
              <option value="">Anyone</option>
              {people.map((u) => <option key={u.id} value={u.username}>{u.display_name}</option>)}
            </select>
          </Field>
          <Field label="Merchant">
            <input class="input" value={val('merchant')} onInput={(e) => set('merchant', (e.target as HTMLInputElement).value)} />
          </Field>
          <Field label="Sort">
            <select class="input" value={val('sort')} onChange={(e) => set('sort', (e.target as HTMLSelectElement).value)}>
              <option value="">Best match / newest</option>
              <option value="date">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="amount">Largest first</option>
              <option value="amount_asc">Smallest first</option>
              <option value="added">Recently added</option>
            </select>
          </Field>
        </div>
      </div>
    </Modal>
  );
}
