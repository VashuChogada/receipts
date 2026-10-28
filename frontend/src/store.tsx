// App-wide state: who's signed in, the household's categories, tags and
// people, toasts, and the two overlays any page can open (capture, review).

import { createContext, type ComponentChildren } from 'preact';
import { useCallback, useContext, useEffect, useMemo, useState } from 'preact/hooks';
import { api, type Category, type Tag, type User } from './api';

interface Toast {
  id: number;
  text: string;
  kind: 'info' | 'error';
}

interface Store {
  user: User;
  setUser: (u: User | null) => void;
  categories: Category[];
  tags: Tag[];
  people: User[];
  merchants: string[];
  reloadTaxonomy: () => Promise<void>;
  /** Bumped after any change to receipts, so lists refetch. */
  version: number;
  bump: () => void;
  toast: (text: string, kind?: Toast['kind']) => void;
  toasts: Toast[];
  captureOpen: boolean;
  openCapture: () => void;
  closeCapture: () => void;
  reviewId: string | null;
  /** Ids to step through with "Next" in the review modal. */
  reviewQueue: string[];
  openReview: (id: string, queue?: string[]) => void;
  closeReview: () => void;
}

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error('useStore outside StoreProvider');
  return s;
}

let toastId = 0;

export function StoreProvider(props: { user: User; setUser: (u: User | null) => void; children: ComponentChildren }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [people, setPeople] = useState<User[]>([]);
  const [merchants, setMerchants] = useState<string[]>([]);
  const [version, setVersion] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [reviewQueue, setReviewQueue] = useState<string[]>([]);

  const reloadTaxonomy = useCallback(async () => {
    const [c, t, p, m] = await Promise.all([
      api.get<Category[]>('/api/categories'),
      api.get<Tag[]>('/api/tags'),
      api.get<User[]>('/api/users'),
      api.get<{ name: string }[]>('/api/merchants'),
    ]);
    setCategories(c);
    setTags(t);
    setPeople(p);
    setMerchants(m.map((x) => x.name));
  }, []);

  useEffect(() => {
    reloadTaxonomy().catch(() => {});
  }, [reloadTaxonomy, version]);

  const toast = useCallback((text: string, kind: Toast['kind'] = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 6000 : 3500);
  }, []);

  const value = useMemo<Store>(
    () => ({
      user: props.user,
      setUser: props.setUser,
      categories,
      tags,
      people,
      merchants,
      reloadTaxonomy,
      version,
      bump: () => setVersion((v) => v + 1),
      toast,
      toasts,
      captureOpen,
      openCapture: () => setCaptureOpen(true),
      closeCapture: () => setCaptureOpen(false),
      reviewId,
      reviewQueue,
      openReview: (id, queue = []) => {
        setReviewQueue(queue);
        setReviewId(id);
      },
      closeReview: () => setReviewId(null),
    }),
    [props.user, props.setUser, categories, tags, people, merchants, reloadTaxonomy, version, toast, toasts, captureOpen, reviewId, reviewQueue],
  );

  return <Ctx.Provider value={value}>{props.children}</Ctx.Provider>;
}

export const categoryColor = (cats: Category[], name: string | null) =>
  cats.find((c) => c.name.toLowerCase() === (name ?? '').toLowerCase())?.color ?? '#64748b';

export const tagColor = (tags: Tag[], name: string) =>
  tags.find((t) => t.name.toLowerCase() === name.toLowerCase())?.color ?? '#64748b';
