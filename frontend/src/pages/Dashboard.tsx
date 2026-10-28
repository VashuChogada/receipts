// Home: this year at a glance, the tax-relevant tags, and what came in last.

import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, qs, type ReceiptSummary } from '../api';
import { RowList } from '../components/ReceiptList';
import { Empty, Icon, Section, SkeletonRows, Spinner } from '../components/ui';
import { fmtMoney } from '../lib/format';
import { useStore } from '../store';

type Sum = { count: number; total: number };

interface Dash {
  year: number;
  this_year: Sum & { tax: number; by_kind: Partial<Record<'hsa' | 'donation' | 'warranty', Sum>> };
  review_count: number;
  processing_count: number;
  hsa_unreimbursed: Sum;
  warranties_expiring: { id: string; merchant: string; product: string | null; expires_on: string }[];
  recent: ReceiptSummary[];
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function Dashboard() {
  const store = useStore();
  const { route } = useLocation();
  const [data, setData] = useState<Dash | null>(null);

  useEffect(() => {
    api.get<Dash>('/api/dashboard').then(setData).catch((e) => store.toast(e.message, 'error'));
  }, [store.version]);

  // Refresh while receipts are being read.
  useEffect(() => {
    if (!data?.processing_count) return;
    const t = setTimeout(() => api.get<Dash>('/api/dashboard').then(setData), 3000);
    return () => clearTimeout(t);
  }, [data]);

  if (!data) {
    return (
      <div class="space-y-5">
        <h1 class="page-title">Receipts</h1>
        <div class="card h-28 animate-pulse" />
        <SkeletonRows n={4} />
      </div>
    );
  }

  const { year, this_year: y } = data;
  const yearRange = { date_from: `${year}-01-01`, date_to: `${year}-12-31` };
  const hsa = y.by_kind.hsa ?? { count: 0, total: 0 };
  const donations = y.by_kind.donation ?? { count: 0, total: 0 };
  const warranties = y.by_kind.warranty ?? { count: 0, total: 0 };
  const open = (r: ReceiptSummary) => (r.status === 'confirmed' ? route(`/receipts/${r.id}`) : store.openReview(r.id));

  if (!data.recent.length && !data.processing_count) {
    return (
      <div class="space-y-5">
        <h1 class="page-title">Receipts</h1>
        <div class="card">
          <Empty title="No receipts yet" icon="camera">
            <p>Scan a receipt and it’s read and filed by year, month and category.</p>
            <button class="btn btn-primary mt-4" onClick={store.openCapture}>
              <Icon name="camera" size={18} /> Scan a receipt
            </button>
          </Empty>
        </div>
      </div>
    );
  }

  return (
    <div class="space-y-6">
      <h1 class="page-title">Receipts</h1>

      {(data.processing_count > 0 || data.review_count > 0) && (
        <div class="space-y-2">
          {data.processing_count > 0 && (
            <p class="flex items-center gap-2 px-1 text-sm">
              <Spinner class="h-4 w-4 text-brand-600" /> Reading {plural(data.processing_count, 'scan')}…
            </p>
          )}
          {data.review_count > 0 && (
            <button class="card flex w-full items-center gap-3 border-amber-300 bg-amber-50 py-3 text-left text-sm dark:border-amber-900 dark:bg-amber-950/40" onClick={() => route('/review')}>
              <Icon name="alert" size={18} class="shrink-0 text-amber-700 dark:text-amber-400" />
              <span class="flex-1">
                <b class="font-medium">{plural(data.review_count, 'scan')} {data.review_count === 1 ? 'needs' : 'need'} a look.</b>{' '}
                <span class="muted">The date or total couldn’t be read.</span>
              </span>
              <Icon name="chevron" size={18} class="muted shrink-0" />
            </button>
          )}
        </div>
      )}

      <div class="grid gap-4 md:grid-cols-[3fr_4fr]">
        <a class="card block" href={`/receipts${qs(yearRange)}`}>
          <p class="muted text-sm">{year} so far</p>
          <p class="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{fmtMoney(y.total)}</p>
          <p class="muted mt-1 text-sm">
            {plural(y.count, 'receipt')} · {fmtMoney(y.tax)} sales tax
          </p>
        </a>

        <div class="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800">
          <KindRow href={`/receipts${qs({ ...yearRange, tag: 'HSA' })}`} label="HSA" value={fmtMoney(hsa.total)}>
            {data.hsa_unreimbursed.count > 0 ? `${fmtMoney(data.hsa_unreimbursed.total)} not reimbursed yet` : plural(hsa.count, 'receipt')}
          </KindRow>
          <KindRow href={`/receipts${qs({ ...yearRange, tag: 'Donation' })}`} label="Donations" value={fmtMoney(donations.total)}>
            {plural(donations.count, 'receipt')}
          </KindRow>
          <KindRow href={`/receipts${qs({ tag: 'Warranty' })}`} label="Warranties" value={String(warranties.count)}>
            {data.warranties_expiring.length
              ? `${data.warranties_expiring.map((w) => w.product ?? w.merchant).join(', ')} ending soon`
              : `added in ${year}`}
          </KindRow>
        </div>
      </div>

      <Section title="Recently added" action={<a class="link text-sm" href="/receipts">All receipts</a>}>
        <RowList items={data.recent} onOpen={open} />
      </Section>
    </div>
  );
}

function KindRow(props: { href: string; label: string; value: string; children: ComponentChildren }) {
  return (
    <a href={props.href} class="flex items-center gap-3 px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-800/50">
      <div class="min-w-0 flex-1">
        <p class="font-medium">{props.label}</p>
        <p class="muted truncate text-xs">{props.children}</p>
      </div>
      <span class="font-medium tabular-nums">{props.value}</span>
      <Icon name="chevron" size={16} class="muted shrink-0" />
    </a>
  );
}
