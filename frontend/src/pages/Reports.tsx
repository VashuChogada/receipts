// A year at a time: the downloads you need at tax time first, then HSA and
// donations, then where the money went.

import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, qs } from '../api';
import { BarList, MonthChart } from '../components/ReceiptList';
import { Empty, Field, Icon, Section, SkeletonRows } from '../components/ui';
import { fmtDate, fmtMoney } from '../lib/format';
import { categoryColor, useStore } from '../store';

interface Overview {
  year: number;
  years: string[];
  totals: { count: number; total: number; tax: number };
  by_month: { month: string; total: number; count: number }[];
  by_category: { name: string; total: number; count: number }[];
  by_merchant: { name: string; total: number; count: number }[];
}

interface HsaReport {
  items: { id: string; txn_date: string; merchant: string; amount: number; patient: string | null; reimbursed: boolean }[];
  total: number;
  unreimbursed: number;
  by_patient: { name: string; total: number; unreimbursed: number }[];
}

interface DonationReport {
  items: { id: string; txn_date: string; organization: string; amount: number; donation_type: string; needs_acknowledgment: boolean }[];
  by_organization: { name: string; ein: string | null; count: number; total: number }[];
  cash_total: number;
  noncash_total: number;
  needs_acknowledgment: { id: string; organization: string; amount: number }[];
}

interface WarrantyReport {
  items: { id: string; merchant: string; product: string | null; expires_on: string | null; expired: boolean }[];
}

export function Reports() {
  const store = useStore();
  const { route } = useLocation();
  const [year, setYear] = useState(new Date().getFullYear());
  const [ov, setOv] = useState<Overview | null>(null);
  const [hsa, setHsa] = useState<HsaReport | null>(null);
  const [don, setDon] = useState<DonationReport | null>(null);
  const [war, setWar] = useState<WarrantyReport | null>(null);
  const [pkgScope, setPkgScope] = useState('all:');

  useEffect(() => {
    Promise.all([
      api.get<Overview>(`/api/reports/overview?year=${year}`),
      api.get<HsaReport>(`/api/reports/hsa?year=${year}`),
      api.get<DonationReport>(`/api/reports/donations?year=${year}`),
      api.get<WarrantyReport>('/api/reports/warranties'),
    ])
      .then(([o, h, d, w]) => {
        setOv(o);
        setHsa(h);
        setDon(d);
        setWar(w);
      })
      .catch((e) => store.toast(e.message, 'error'));
  }, [year, store.version]);

  if (!ov || !hsa || !don || !war) {
    return (
      <div class="space-y-4">
        <h1 class="page-title">Reports</h1>
        <SkeletonRows n={4} />
      </div>
    );
  }

  const years = Array.from(new Set([String(new Date().getFullYear()), ...ov.years])).sort().reverse();
  const yearRange = { date_from: `${year}-01-01`, date_to: `${year}-12-31` };
  const zip = (scope: Record<string, string>, label: string) =>
    `/api/export.zip${qs({ ...yearRange, ...scope, name: `${label} ${year}`, status: 'confirmed' })}`;
  const [scopeKind, scopeName] = pkgScope.split(':');
  const pkgParams = { ...yearRange, [scopeKind === 'tag' ? 'tag' : 'category']: scopeName || undefined, name: `${scopeName || 'All'} ${year}`, status: 'confirmed' };
  const openMonth = (m: string) => {
    const [y, mo] = m.split('-').map(Number);
    const last = new Date(y, mo, 0).getDate();
    route(`/receipts${qs({ date_from: `${m}-01`, date_to: `${m}-${last}` })}`);
  };

  return (
    <div class="space-y-7">
      <div class="space-y-3">
        <h1 class="page-title">Reports</h1>
        <div class="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
          {years.map((y) => (
            <button key={y} class={`pill ${Number(y) === year ? 'pill-on' : ''}`} onClick={() => setYear(Number(y))} aria-pressed={Number(y) === year}>
              {y}
            </button>
          ))}
        </div>
      </div>

      <Section title={`Tax time: download ${year}`}>
        <div class="card space-y-3">
          <p class="muted text-sm">A ZIP with a spreadsheet and every original scan, for your accountant or an HSA claim.</p>
          <div class="grid gap-2 sm:grid-cols-3">
            <a class="btn justify-start" href={zip({ tag: 'HSA' }, 'HSA')} download>
              <Icon name="download" size={18} /> HSA receipts
            </a>
            <a class="btn justify-start" href={zip({ tag: 'Donation' }, 'Donations')} download>
              <Icon name="download" size={18} /> Donations
            </a>
            <a class="btn justify-start" href={zip({}, 'Receipts')} download>
              <Icon name="download" size={18} /> Everything
            </a>
          </div>
          <details class="text-sm">
            <summary class="link cursor-pointer">Something else</summary>
            <div class="mt-3 flex flex-wrap items-end gap-2">
              <Field label="Only" class="min-w-48 flex-1">
                <select class="input" value={pkgScope} onChange={(e) => setPkgScope((e.target as HTMLSelectElement).value)}>
                  <option value="all:">Every filed receipt</option>
                  <optgroup label="Tags">{store.tags.map((t) => <option key={t.name} value={`tag:${t.name}`}>{t.name}</option>)}</optgroup>
                  <optgroup label="Categories">{store.categories.map((c) => <option key={c.name} value={`category:${c.name}`}>{c.name}</option>)}</optgroup>
                </select>
              </Field>
              <a class="btn" href={`/api/export.zip${qs(pkgParams)}`} download>ZIP</a>
              <a class="btn" href={`/api/export.csv${qs(pkgParams)}`} download>CSV</a>
            </div>
          </details>
        </div>
      </Section>

      <div class="grid gap-7 md:grid-cols-2">
        <Section title="HSA" action={<a class="link text-sm" href={`/receipts${qs({ tag: 'HSA', ...yearRange })}`}>See all</a>}>
          <div class="card space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <Stat label={`Spent in ${year}`} value={fmtMoney(hsa.total)} />
              <Stat label="Not reimbursed" value={fmtMoney(hsa.unreimbursed)} accent={hsa.unreimbursed ? 'text-red-700 dark:text-red-400' : ''} />
            </div>
            {hsa.by_patient.length > 0 && (
              <table class="w-full text-sm">
                <thead class="muted text-left text-xs">
                  <tr>
                    <th class="py-1 font-medium">Patient</th>
                    <th class="text-right font-medium">Total</th>
                    <th class="text-right font-medium">Not reimbursed</th>
                  </tr>
                </thead>
                <tbody>
                  {hsa.by_patient.map((p) => (
                    <tr key={p.name} class="border-t border-neutral-100 dark:border-neutral-800">
                      <td class="py-1.5">{p.name}</td>
                      <td class="text-right tabular-nums">{fmtMoney(p.total)}</td>
                      <td class="text-right tabular-nums">{fmtMoney(p.unreimbursed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {!hsa.items.length && <p class="muted text-sm">Tag medical receipts HSA when you scan them to track what you can claim later.</p>}
          </div>
        </Section>

        <Section title="Donations" action={<a class="link text-sm" href={`/receipts${qs({ tag: 'Donation', ...yearRange })}`}>See all</a>}>
          <div class="card space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <Stat label="Cash and card" value={fmtMoney(don.cash_total)} />
              <Stat label="Non-cash" value={fmtMoney(don.noncash_total)} />
            </div>
            {don.needs_acknowledgment.length > 0 && (
              <div class="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <p class="flex items-center gap-1.5 font-medium">
                  <Icon name="alert" size={16} /> Get an acknowledgment letter for
                </p>
                <ul class="mt-1 list-disc pl-5">
                  {don.needs_acknowledgment.map((d) => (
                    <li key={d.id}>
                      <a class="underline" href={`/receipts/${d.id}`}>{d.organization}</a> · {fmtMoney(d.amount)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {don.by_organization.length > 0 ? (
              <table class="w-full text-sm">
                <thead class="muted text-left text-xs">
                  <tr>
                    <th class="py-1 font-medium">Organization</th>
                    <th class="font-medium">EIN</th>
                    <th class="text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {don.by_organization.map((o) => (
                    <tr key={o.name} class="border-t border-neutral-100 dark:border-neutral-800">
                      <td class="py-1.5">{o.name}</td>
                      <td class="muted">{o.ein ?? '—'}</td>
                      <td class="text-right tabular-nums">{fmtMoney(o.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p class="muted text-sm">Tag donation receipts Donation to build a year-end list.</p>
            )}
          </div>
        </Section>
      </div>

      <Section title={`Spending in ${year}`}>
        {ov.totals.count === 0 ? (
          <div class="card">
            <Empty title={`No receipts dated ${year}`} icon="chart" />
          </div>
        ) : (
          <div class="space-y-4">
            <div class="card">
              <div class="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span class="text-2xl font-semibold tracking-tight tabular-nums">{fmtMoney(ov.totals.total)}</span>
                <span class="muted text-sm">
                  {ov.totals.count} {ov.totals.count === 1 ? 'receipt' : 'receipts'} · {fmtMoney(ov.totals.tax)} sales tax
                </span>
              </div>
              <MonthChart rows={ov.by_month} year={year} onPick={openMonth} />
            </div>
            <div class="grid gap-4 md:grid-cols-2">
              <div class="card">
                <h3 class="mb-3 text-sm font-medium">By category</h3>
                <BarList rows={ov.by_category} colorOf={(n) => categoryColor(store.categories, n)} onPick={(n) => route(`/receipts${qs({ ...yearRange, category: n })}`)} />
              </div>
              <div class="card">
                <h3 class="mb-3 text-sm font-medium">Top merchants</h3>
                <BarList rows={ov.by_merchant.slice(0, 8)} colorOf={() => 'var(--color-neutral-400)'} onPick={(n) => route(`/receipts${qs({ ...yearRange, merchant: n })}`)} />
              </div>
            </div>
          </div>
        )}
      </Section>

      {war.items.length > 0 && (
        <Section title="Warranties">
          <div class="card divide-y divide-neutral-100 p-0 text-sm dark:divide-neutral-800">
            {war.items.map((w) => (
              <a key={w.id} href={`/receipts/${w.id}`} class={`flex justify-between gap-3 px-4 py-3 ${w.expired ? 'muted line-through' : ''}`}>
                <span>{w.product ?? w.merchant}</span>
                <span class="muted">{w.expires_on ? `until ${fmtDate(w.expires_on)}` : 'No end date'}</span>
              </a>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function Stat(props: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <p class="muted text-xs">{props.label}</p>
      <p class={`mt-0.5 text-xl font-semibold tabular-nums ${props.accent ?? ''}`}>{props.value}</p>
    </div>
  );
}
