import { useEffect, useState } from 'preact/hooks';
import { LocationProvider, Route, Router, useLocation } from 'preact-iso';
import { api, server, type AuthState, type User } from './api';
import { CaptureFlow } from './components/CaptureFlow';
import { ReviewModal } from './components/ReviewModal';
import { Icon, Spinner } from './components/ui';
import { setCurrency } from './lib/format';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { ReceiptDetail } from './pages/ReceiptDetail';
import { Receipts } from './pages/Receipts';
import { Reports } from './pages/Reports';
import { Review } from './pages/Review';
import { Settings } from './pages/Settings';
import { StoreProvider, useStore } from './store';

export function App() {
  const [state, setState] = useState<AuthState | null>(null);

  useEffect(() => {
    api
      .get<AuthState>('/api/auth/state')
      .then((s) => {
        if (s.server) {
          Object.assign(server, s.server);
          setCurrency(s.server.currency);
        }
        setState(s);
      })
      .catch(() => setState({ needs_setup: false, user: null }));
    const out = () => setState((s) => (s ? { ...s, user: null } : s));
    window.addEventListener('signed-out', out);
    return () => window.removeEventListener('signed-out', out);
  }, []);

  if (!state) return <div class="flex min-h-dvh items-center justify-center"><Spinner /></div>;
  const setUser = (user: User | null) => setState({ needs_setup: false, user });
  if (!state.user) return <Login setup={state.needs_setup} onUser={setUser} />;

  return (
    <LocationProvider>
      <StoreProvider user={state.user} setUser={setUser}>
        <Shell />
      </StoreProvider>
    </LocationProvider>
  );
}

const NAV = [
  { href: '/', label: 'Home', icon: 'home' },
  { href: '/receipts', label: 'Receipts', icon: 'list' },
  { href: '/reports', label: 'Reports', icon: 'chart' },
  { href: '/settings', label: 'Settings', icon: 'gear' },
];

function Shell() {
  const store = useStore();
  const { path } = useLocation();

  // A new page starts at the top, not at the last page's scroll position.
  useEffect(() => window.scrollTo(0, 0), [path]);

  const active = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
  const tab = (n: (typeof NAV)[number]) => (
    <a
      key={n.href}
      href={n.href}
      aria-current={active(n.href) ? 'page' : undefined}
      class={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${active(n.href) ? 'font-medium text-neutral-900 dark:text-white' : 'text-neutral-500 dark:text-neutral-400'}`}
    >
      <Icon name={n.icon} size={22} />
      {n.label}
    </a>
  );

  return (
    <div class="min-h-dvh pb-24 md:pb-8">
      <header class="sticky top-0 z-20 hidden border-b border-neutral-200 bg-white/95 md:block dark:border-neutral-800 dark:bg-neutral-950/95">
        <nav class="mx-auto flex max-w-4xl items-center gap-1 px-4 py-2">
          <a href="/" class="mr-4 flex items-center gap-2 font-semibold">
            <img src="/favicon.svg" alt="" class="h-6 w-6" /> Receipts
          </a>
          {NAV.map((n) => (
            <a
              key={n.href}
              href={n.href}
              aria-current={active(n.href) ? 'page' : undefined}
              class={`rounded-lg px-3 py-1.5 text-sm ${active(n.href) ? 'bg-neutral-100 font-medium text-neutral-900 dark:bg-neutral-800 dark:text-white' : 'text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white'}`}
            >
              {n.label}
            </a>
          ))}
          <div class="flex-1" />
          <button class="btn btn-primary" onClick={store.openCapture}>
            <Icon name="camera" size={18} /> Scan
          </button>
        </nav>
      </header>

      <main class="mx-auto max-w-4xl px-4 pt-[max(env(safe-area-inset-top),1.25rem)] md:pt-8">
        <Router>
          <Route path="/" component={Dashboard} />
          <Route path="/receipts" component={Receipts} />
          <Route path="/receipts/:id" component={ReceiptDetail} />
          <Route path="/review" component={Review} />
          <Route path="/reports" component={Reports} />
          <Route path="/settings" component={Settings} />
          <Route default component={Dashboard} />
        </Router>
      </main>

      {/* Phones: four tabs with Scan in the middle, one thumb-tap away. */}
      <nav class="safe-bottom fixed inset-x-0 bottom-0 z-20 border-t border-neutral-200 bg-white/95 md:hidden dark:border-neutral-800 dark:bg-neutral-950/95">
        <div class="grid grid-cols-5 items-center">
          {NAV.slice(0, 2).map(tab)}
          <div class="flex justify-center">
            <button
              class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-700 text-white transition active:scale-95 dark:bg-brand-600"
              onClick={store.openCapture}
              aria-label="Scan a receipt"
            >
              <Icon name="camera" size={24} />
            </button>
          </div>
          {NAV.slice(2).map(tab)}
        </div>
      </nav>

      <CaptureFlow />
      <ReviewModal />

      <div class="pointer-events-none fixed inset-x-0 top-3 z-[60] flex flex-col items-center gap-2 px-4" role="status" aria-live="polite">
        {store.toasts.map((t) => (
          <div key={t.id} class={`pointer-events-auto max-w-md rounded-lg px-4 py-2 text-sm shadow-lg ${t.kind === 'error' ? 'bg-red-700 text-white' : 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'}`}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
