// Amounts and dates in the browser's language; the currency is the server's
// CURRENCY setting, applied once /api/auth/state answers.
let money = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });

export function setCurrency(code: string) {
  try {
    money = new Intl.NumberFormat(undefined, { style: 'currency', currency: code });
  } catch {
    // An unknown code keeps the previous format.
  }
}

export const fmtMoney = (n: number | null | undefined) => (n === null || n === undefined ? '—' : money.format(n));

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!iso) return 'No date';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, opts);
}

export function fmtDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...a: A) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

export const statusLabel: Record<string, string> = {
  queued: 'Waiting',
  processing: 'Reading',
  review: 'To review',
  confirmed: 'Filed',
  failed: 'Couldn’t read',
};
