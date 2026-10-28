import { previewUrl, type ReceiptSummary } from '../api';
import { fmtDate, fmtMoney, statusLabel } from '../lib/format';
import { CategoryChip, Icon, TagChip } from './ui';

export function ReceiptRow(props: { r: ReceiptSummary; onOpen: (r: ReceiptSummary) => void }) {
  const r = props.r;
  const pending = r.status !== 'confirmed';
  return (
    <button
      class="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-neutral-50 active:bg-neutral-100 dark:hover:bg-neutral-800/50 dark:active:bg-neutral-800"
      onClick={() => props.onOpen(r)}
    >
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate font-medium">{r.merchant ?? 'Unknown merchant'}</span>
          {r.needs_acknowledgment && (
            <span title="Needs the charity's acknowledgment" class="shrink-0 text-amber-600">
              <Icon name="alert" size={14} />
            </span>
          )}
        </div>
        <div class="muted mt-0.5 flex min-w-0 items-center gap-x-2 overflow-hidden text-xs">
          <span class="shrink-0">{fmtDate(r.txn_date, { month: 'short', day: 'numeric' })}</span>
          {pending ? (
            <span class={`shrink-0 font-medium ${r.status === 'failed' ? 'text-amber-700 dark:text-amber-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
              {r.status === 'review' ? 'Needs a look' : statusLabel[r.status]}
            </span>
          ) : (
            <CategoryChip name={r.category} />
          )}
          {r.tags.map((t) => (
            <TagChip key={t} name={t} note={t === 'HSA' && r.reimbursed === false ? 'to claim' : undefined} />
          ))}
        </div>
      </div>
      <div class="shrink-0 text-right font-medium tabular-nums">{fmtMoney(r.total)}</div>
    </button>
  );
}

/** Rows under a heading per month ("October 2026 · $482.87"), newest first as given. */
export function MonthGroups(props: { items: ReceiptSummary[]; onOpen: (r: ReceiptSummary) => void }) {
  const groups: { key: string; items: ReceiptSummary[] }[] = [];
  for (const r of props.items) {
    const key = r.txn_date?.slice(0, 7) ?? '';
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(r);
    else groups.push({ key, items: [r] });
  }
  return (
    <div class="space-y-4">
      {groups.map((g) => (
        <section key={g.key}>
          <div class="mb-1.5 flex items-baseline justify-between px-1 text-sm">
            <h3 class="font-semibold">{g.key ? fmtDate(`${g.key}-01`, { month: 'long', year: 'numeric' }) : 'No date'}</h3>
            <span class="muted tabular-nums">{fmtMoney(g.items.reduce((s, r) => s + (r.total ?? 0), 0))}</span>
          </div>
          <RowList items={g.items} onOpen={props.onOpen} />
        </section>
      ))}
    </div>
  );
}

export function RowList(props: { items: ReceiptSummary[]; onOpen: (r: ReceiptSummary) => void }) {
  return (
    <div class="card divide-y divide-neutral-100 overflow-hidden p-0 dark:divide-neutral-800">
      {props.items.map((r) => (
        <ReceiptRow key={r.id} r={r} onOpen={props.onOpen} />
      ))}
    </div>
  );
}

export function ReceiptGrid(props: { items: ReceiptSummary[]; onOpen: (r: ReceiptSummary) => void }) {
  return (
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {props.items.map((r) => (
        <button key={r.id} class="card overflow-hidden p-0 text-left" onClick={() => props.onOpen(r)}>
          <img
            src={previewUrl({ id: r.id, updated_at: r.created_at }, 320)}
            alt=""
            loading="lazy"
            class="aspect-[3/4] w-full bg-neutral-100 object-cover object-top dark:bg-neutral-800 dark:opacity-90"
          />
          <div class="border-t border-neutral-200 p-2 dark:border-neutral-800">
            <div class="truncate text-sm font-medium">{r.merchant ?? 'Unknown'}</div>
            <div class="muted flex justify-between text-xs">
              <span>{fmtDate(r.txn_date, { month: 'short', day: 'numeric', year: '2-digit' })}</span>
              <span class="font-medium text-neutral-700 tabular-nums dark:text-neutral-200">{fmtMoney(r.total)}</span>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

/** Horizontal bars with each row's share of the whole. */
export function BarList(props: { rows: { name: string; total: number; count?: number }[]; colorOf?: (name: string) => string; onPick?: (name: string) => void }) {
  const max = Math.max(1, ...props.rows.map((r) => r.total || 0));
  const sum = props.rows.reduce((s, r) => s + (r.total || 0), 0) || 1;
  return (
    <ul class="space-y-3">
      {props.rows.map((r) => (
        <li key={r.name}>
          <button class="w-full text-left disabled:cursor-default" onClick={() => props.onPick?.(r.name)} disabled={!props.onPick}>
            <div class="mb-1 flex items-baseline justify-between gap-3 text-sm">
              <span class="truncate">{r.name}</span>
              <span class="shrink-0 tabular-nums">
                {fmtMoney(r.total)}
                <span class="muted ml-1.5 inline-block w-9 text-right text-xs">{Math.round(((r.total || 0) / sum) * 100)}%</span>
              </span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
              <div class="h-full rounded-full" style={{ width: `${((r.total || 0) / max) * 100}%`, background: props.colorOf?.(r.name) ?? 'var(--color-brand-600)' }} />
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

const compact = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });

/** Monthly totals as columns, hand-drawn SVG; the current month in the accent color. */
export function MonthChart(props: { rows: { month: string; total: number }[]; year: number; onPick?: (month: string) => void }) {
  const months = Array.from({ length: 12 }, (_, i) => `${props.year}-${String(i + 1).padStart(2, '0')}`);
  const byMonth = new Map(props.rows.map((r) => [r.month, r.total]));
  const max = Math.max(1, ...props.rows.map((r) => r.total));
  const now = new Date();
  const current = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const W = 360;
  const H = 120;
  const top = 16;
  const bw = W / 12;
  return (
    <svg viewBox={`0 0 ${W} ${top + H + 20}`} class="max-h-56 w-full" role="img" aria-label={`Spending by month in ${props.year}`}>
      <line x1="0" x2={W} y1={top + H} y2={top + H} class="stroke-neutral-200 dark:stroke-neutral-800" />
      {months.map((m, i) => {
        const v = byMonth.get(m) ?? 0;
        const h = (v / max) * H;
        const label = new Date(props.year, i, 1).toLocaleDateString(undefined, { month: 'short' });
        return (
          <g key={m} class={props.onPick && v ? 'cursor-pointer' : ''} onClick={() => v && props.onPick?.(m)}>
            <title>{`${label}: ${fmtMoney(v)}`}</title>
            <rect
              x={i * bw + 5}
              y={top + H - h}
              width={bw - 10}
              height={Math.max(h, v ? 2 : 0)}
              rx="2"
              class={m === current ? 'fill-brand-600 dark:fill-brand-500' : 'fill-neutral-300 dark:fill-neutral-600'}
            />
            {v > 0 && (
              <text x={i * bw + bw / 2} y={top + H - h - 4} text-anchor="middle" class="fill-neutral-500 text-[8.5px] tabular-nums dark:fill-neutral-400">
                {compact.format(v)}
              </text>
            )}
            <text x={i * bw + bw / 2} y={top + H + 14} text-anchor="middle" class="fill-neutral-500 text-[9px] dark:fill-neutral-400">
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
