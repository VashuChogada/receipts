import { useEffect, useState } from 'preact/hooks';
import { api, type SearchResult } from '../api';
import { ReceiptRow } from '../components/ReceiptList';
import { Empty, Section, Spinner } from '../components/ui';
import { useStore } from '../store';

export function Review() {
  const store = useStore();
  const [toReview, setToReview] = useState<SearchResult | null>(null);
  const [failed, setFailed] = useState<SearchResult | null>(null);
  const [reading, setReading] = useState<SearchResult | null>(null);

  const load = () =>
    Promise.all([
      api.get<SearchResult>('/api/receipts?status=review&sort=added&limit=200'),
      api.get<SearchResult>('/api/receipts?status=failed&sort=added&limit=200'),
      api.get<SearchResult>('/api/receipts?status=processing&limit=50'),
      api.get<SearchResult>('/api/receipts?status=queued&limit=50'),
    ]).then(([r, f, p, q]) => {
      setToReview(r);
      setFailed(f);
      setReading({ ...p, items: [...p.items, ...q.items], total: p.total + q.total });
    });

  useEffect(() => {
    load().catch((e) => store.toast(e.message, 'error'));
  }, [store.version]);

  useEffect(() => {
    if (!reading?.total) return;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [reading]);

  if (!toReview || !failed || !reading) return <div class="flex justify-center p-10"><Spinner /></div>;

  const queue = [...toReview.items, ...failed.items].map((r) => r.id);
  const nothing = !queue.length && !reading.total;

  return (
    <div class="space-y-5">
      <div class="flex items-center justify-between">
        <h1 class="page-title">Review queue</h1>
        {queue.length > 0 && (
          <button class="btn btn-primary" onClick={() => store.openReview(queue[0], queue)}>
            Start ({queue.length})
          </button>
        )}
      </div>

      {nothing && (
        <Empty title="All caught up" icon="check">
          New scans land here until you confirm what was read.
        </Empty>
      )}

      {reading.total > 0 && (
        <Section title="Being read">
          <div class="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800">
            {reading.items.map((r) => <ReceiptRow key={r.id} r={r} onOpen={() => store.openReview(r.id, queue)} />)}
          </div>
        </Section>
      )}

      {toReview.items.length > 0 && (
        <Section title="Check and confirm">
          <div class="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800">
            {toReview.items.map((r) => <ReceiptRow key={r.id} r={r} onOpen={() => store.openReview(r.id, queue)} />)}
          </div>
        </Section>
      )}

      {failed.items.length > 0 && (
        <Section title="Couldn’t be read — fill in by hand">
          <div class="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800">
            {failed.items.map((r) => <ReceiptRow key={r.id} r={r} onOpen={() => store.openReview(r.id, queue)} />)}
          </div>
        </Section>
      )}
    </div>
  );
}
