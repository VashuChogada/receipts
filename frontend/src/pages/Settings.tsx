import { useEffect, useState } from 'preact/hooks';
import { api, type Rule, type User } from '../api';
import { Field, Icon, Section, Spinner } from '../components/ui';
import { useStore } from '../store';

export function Settings() {
  const store = useStore();
  return (
    <div class="space-y-6">
      <h1 class="page-title">Settings</h1>
      <Account />
      {store.user.role === 'admin' && <People />}
      <Categories />
      <Tags />
      {/* Rarely needed: tucked away so the page stays short. */}
      <details class="group">
        <summary class="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-neutral-600 dark:text-neutral-300">
          <Icon name="chevron" size={16} class="transition group-open:rotate-90" /> Advanced
        </summary>
        <div class="mt-4 space-y-6">
          <Rules />
          <Aliases />
          <Maintenance />
        </div>
      </details>
    </div>
  );
}

function Account() {
  const store = useStore();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const change = async (e: Event) => {
    e.preventDefault();
    try {
      await api.post('/api/auth/password', { current, new: next });
      store.toast('Password changed');
      setCurrent('');
      setNext('');
    } catch (err) {
      store.toast((err as Error).message, 'error');
    }
  };
  return (
    <Section title="Your account">
      <div class="card space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <p class="font-medium">{store.user.display_name}</p>
            <p class="muted text-sm">
              @{store.user.username} · {store.user.role}
            </p>
          </div>
          <button
            class="btn"
            onClick={async () => {
              await api.post('/api/auth/logout');
              store.setUser(null);
            }}
          >
            Sign out
          </button>
        </div>
        <form class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={change}>
          <input class="input" type="password" placeholder="Current password" autoComplete="current-password" value={current} onInput={(e) => setCurrent((e.target as HTMLInputElement).value)} required />
          <input class="input" type="password" placeholder="New password (8+)" autoComplete="new-password" minLength={8} value={next} onInput={(e) => setNext((e.target as HTMLInputElement).value)} required />
          <button class="btn">Change</button>
        </form>
      </div>
    </Section>
  );
}

function People() {
  const store = useStore();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ username: '', display_name: '', password: '', role: 'member' });
  const load = () => api.get<User[]>('/api/users').then(setUsers);
  useEffect(() => {
    load();
  }, []);
  const add = async (e: Event) => {
    e.preventDefault();
    try {
      await api.post('/api/users', form);
      setForm({ username: '', display_name: '', password: '', role: 'member' });
      store.toast(`Added ${form.username}`);
      load();
      store.reloadTaxonomy();
    } catch (err) {
      store.toast((err as Error).message, 'error');
    }
  };
  const patch = async (u: User, body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/users/${u.id}`, body);
      load();
    } catch (err) {
      store.toast((err as Error).message, 'error');
    }
  };
  return (
    <Section title="Household">
      <div class="card space-y-3">
        <ul class="divide-y divide-neutral-100 dark:divide-neutral-800">
          {users.map((u) => (
            <li key={u.id} class="flex flex-wrap items-center gap-2 py-2 text-sm">
              <span class={`flex-1 ${u.disabled ? 'muted line-through' : ''}`}>
                {u.display_name} <span class="muted">@{u.username}</span>
              </span>
              <select class="input min-h-8 w-auto py-1 text-sm" value={u.role} onChange={(e) => patch(u, { role: (e.target as HTMLSelectElement).value })} disabled={u.id === store.user.id}>
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
              <button
                class="btn min-h-8 text-xs"
                onClick={() => {
                  const pw = prompt(`New password for ${u.username} (8+ characters)`);
                  if (pw) patch(u, { password: pw }).then(() => store.toast('Password reset'));
                }}
              >
                Reset password
              </button>
              {u.id !== store.user.id && (
                <button class="btn min-h-8 text-xs" onClick={() => patch(u, { disabled: !u.disabled })}>
                  {u.disabled ? 'Enable' : 'Disable'}
                </button>
              )}
            </li>
          ))}
        </ul>
        <form class="grid gap-2 sm:grid-cols-2" onSubmit={add}>
          <input class="input" placeholder="username" autoCapitalize="none" pattern="[A-Za-z0-9._-]{2,32}" value={form.username} onInput={(e) => setForm({ ...form, username: (e.target as HTMLInputElement).value })} required />
          <input class="input" placeholder="Name" value={form.display_name} onInput={(e) => setForm({ ...form, display_name: (e.target as HTMLInputElement).value })} />
          <input class="input" type="password" placeholder="Password (8+)" minLength={8} autoComplete="new-password" value={form.password} onInput={(e) => setForm({ ...form, password: (e.target as HTMLInputElement).value })} required />
          <button class="btn btn-primary">Add person</button>
        </form>
      </div>
    </Section>
  );
}

function Categories() {
  const store = useStore();
  const [name, setName] = useState('');
  const call = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      await store.reloadTaxonomy();
      if (ok) store.toast(ok);
    } catch (e) {
      store.toast((e as Error).message, 'error');
    }
  };
  return (
    <Section title="Categories" action={<span class="muted text-xs">Each is a folder under YYYY/MM/</span>}>
      <div class="card space-y-2">
        {store.categories.map((c) => (
          <div key={c.name} class="flex items-center gap-2 text-sm">
            <input type="color" value={c.color} class="h-8 w-8 cursor-pointer rounded border-0 bg-transparent" onChange={(e) => call(() => api.patch(`/api/categories/${encodeURIComponent(c.name)}`, { color: (e.target as HTMLInputElement).value }))} />
            <span class="flex-1">{c.name} <span class="muted">· {c.count}</span></span>
            <button
              class="btn min-h-8 text-xs"
              onClick={() => {
                const n = prompt('Rename category (filed receipts move to the new folder)', c.name);
                if (n && n !== c.name) call(() => api.patch(`/api/categories/${encodeURIComponent(c.name)}`, { name: n }), 'Renamed');
              }}
            >
              Rename
            </button>
            {c.name !== 'Other' && (
              <button
                class="btn btn-danger min-h-8 px-2"
                aria-label={`Delete ${c.name}`}
                onClick={() => confirm(`Delete ${c.name}? Its ${c.count} receipts move to Other.`) && call(() => api.del(`/api/categories/${encodeURIComponent(c.name)}?move_to=Other`), 'Deleted')}
              >
                <Icon name="trash" size={14} />
              </button>
            )}
          </div>
        ))}
        <form
          class="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            call(() => api.post('/api/categories', { name, color: '#64748b' }), 'Added').then(() => setName(''));
          }}
        >
          <input class="input" placeholder="New category" value={name} onInput={(e) => setName((e.target as HTMLInputElement).value)} required />
          <button class="btn">Add</button>
        </form>
      </div>
    </Section>
  );
}

function Tags() {
  const store = useStore();
  const [name, setName] = useState('');
  const call = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await store.reloadTaxonomy();
    } catch (e) {
      store.toast((e as Error).message, 'error');
    }
  };
  const kindLabel: Record<string, string> = { hsa: 'HSA fields', donation: 'donation fields', warranty: 'warranty fields' };
  return (
    <Section title="Tags">
      <div class="card space-y-2">
        {store.tags.map((t) => (
          <div key={t.name} class="flex items-center gap-2 text-sm">
            <input type="color" value={t.color} class="h-8 w-8 cursor-pointer rounded border-0 bg-transparent" onChange={(e) => call(() => api.patch(`/api/tags/${encodeURIComponent(t.name)}`, { name: t.name, color: (e.target as HTMLInputElement).value }))} />
            <span class="flex-1">
              {t.name} <span class="muted">· {t.count}{t.kind !== 'plain' && ` · ${kindLabel[t.kind]}`}</span>
            </span>
            <button
              class="btn min-h-8 text-xs"
              onClick={() => {
                const n = prompt('Rename tag', t.name);
                if (n && n !== t.name) call(() => api.patch(`/api/tags/${encodeURIComponent(t.name)}`, { name: n, color: t.color }));
              }}
            >
              Rename
            </button>
            {t.kind === 'plain' && (
              <button class="btn btn-danger min-h-8 px-2" aria-label={`Delete ${t.name}`} onClick={() => confirm(`Delete #${t.name}?`) && call(() => api.del(`/api/tags/${encodeURIComponent(t.name)}`))}>
                <Icon name="trash" size={14} />
              </button>
            )}
          </div>
        ))}
        <form
          class="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            call(() => api.post('/api/tags', { name, color: '#0f766e' })).then(() => setName(''));
          }}
        >
          <input class="input" placeholder="New tag (e.g. Business, Kids)" value={name} onInput={(e) => setName((e.target as HTMLInputElement).value)} required />
          <button class="btn">Add</button>
        </form>
      </div>
    </Section>
  );
}

function Rules() {
  const store = useStore();
  const [rules, setRules] = useState<Rule[]>([]);
  const [form, setForm] = useState({ pattern: '', field: 'merchant', is_regex: false, category: '', tag: '' });
  const [test, setTest] = useState({ merchant: '', text: '' });
  const [result, setResult] = useState<{ category: string | null; tags: string[] } | null>(null);
  const load = () => api.get<Rule[]>('/api/rules').then(setRules);
  useEffect(() => {
    load();
  }, [store.version]);
  const add = async (e: Event) => {
    e.preventDefault();
    try {
      await api.post('/api/rules', { ...form, category: form.category || null, tag: form.tag || null });
      setForm({ ...form, pattern: '' });
      load();
    } catch (err) {
      store.toast((err as Error).message, 'error');
    }
  };
  const user = rules.filter((r) => r.source === 'user');
  const defaults = rules.filter((r) => r.source === 'default');
  const ruleRow = (r: Rule) => (
    <li key={r.id} class="flex items-start gap-2 py-1.5 text-sm">
      <div class="min-w-0 flex-1">
        <code class="text-xs break-all">{r.field}: {r.is_regex ? `/${r.pattern}/` : `contains “${r.pattern}”`}</code>
        <div class="muted text-xs">→ {[r.category, r.tag && `#${r.tag}`].filter(Boolean).join(' + ')}</div>
      </div>
      <button class="btn btn-ghost min-h-7 px-1.5" aria-label="Delete rule" onClick={() => api.del(`/api/rules/${r.id}`).then(load)}>
        <Icon name="x" size={14} />
      </button>
    </li>
  );
  return (
    <Section title="Auto-categorize rules">
      <div class="card space-y-3">
        <p class="muted text-sm">Your rules run before the built-in ones. Ticking “Always file … under …” when confirming adds one here.</p>
        {user.length > 0 ? <ul class="divide-y divide-neutral-100 dark:divide-neutral-800">{user.map(ruleRow)}</ul> : <p class="muted text-sm">No rules of your own yet.</p>}
        <form class="grid gap-2 sm:grid-cols-2" onSubmit={add}>
          <input class="input sm:col-span-2" placeholder="Pattern, e.g. trader joe" value={form.pattern} onInput={(e) => setForm({ ...form, pattern: (e.target as HTMLInputElement).value })} required />
          <select class="input" value={form.field} onChange={(e) => setForm({ ...form, field: (e.target as HTMLSelectElement).value })}>
            <option value="merchant">Match the merchant</option>
            <option value="text">Match the receipt text</option>
          </select>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_regex} onChange={(e) => setForm({ ...form, is_regex: (e.target as HTMLInputElement).checked })} /> Regular expression
          </label>
          <select class="input" value={form.category} onChange={(e) => setForm({ ...form, category: (e.target as HTMLSelectElement).value })}>
            <option value="">No category</option>
            {store.categories.map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
          <select class="input" value={form.tag} onChange={(e) => setForm({ ...form, tag: (e.target as HTMLSelectElement).value })}>
            <option value="">No tag</option>
            {store.tags.map((t) => <option key={t.name}>{t.name}</option>)}
          </select>
          <button class="btn btn-primary sm:col-span-2">Add rule</button>
        </form>
        <details>
          <summary class="cursor-pointer text-sm font-medium">Test the rules</summary>
          <div class="mt-2 grid gap-2">
            <Field label="Merchant"><input class="input" value={test.merchant} onInput={(e) => setTest({ ...test, merchant: (e.target as HTMLInputElement).value })} /></Field>
            <Field label="Receipt text"><textarea class="input" rows={2} value={test.text} onInput={(e) => setTest({ ...test, text: (e.target as HTMLTextAreaElement).value })} /></Field>
            <button class="btn" onClick={() => api.post<{ category: string | null; tags: string[] }>('/api/rules/test', test).then(setResult)}>Test</button>
            {result && <p class="text-sm">→ <b>{result.category ?? 'no category'}</b>{result.tags.length > 0 && ` + ${result.tags.map((t) => `#${t}`).join(' ')}`}</p>}
          </div>
        </details>
        <details>
          <summary class="cursor-pointer text-sm font-medium">Built-in rules ({defaults.length})</summary>
          <ul class="mt-1 divide-y divide-neutral-100 dark:divide-neutral-800">{defaults.map(ruleRow)}</ul>
        </details>
      </div>
    </Section>
  );
}

function Aliases() {
  const [aliases, setAliases] = useState<{ raw_key: string; canonical: string }[]>([]);
  const load = () => api.get<{ raw_key: string; canonical: string }[]>('/api/merchant-aliases').then(setAliases);
  useEffect(() => {
    load();
  }, []);
  if (!aliases.length) return null;
  return (
    <Section title="Learned merchant names">
      <details class="card">
        <summary class="cursor-pointer text-sm">{aliases.length} OCR spellings mapped to the names you confirmed</summary>
        <ul class="mt-2 space-y-1 text-sm">
          {aliases.map((a) => (
            <li key={a.raw_key} class="flex items-center gap-2">
              <code class="muted flex-1 truncate text-xs">{a.raw_key}</code>→<span>{a.canonical}</span>
              <button class="btn btn-ghost min-h-7 px-1.5" aria-label="Forget" onClick={() => api.del(`/api/merchant-aliases/${encodeURIComponent(a.raw_key)}`).then(load)}>
                <Icon name="x" size={14} />
              </button>
            </li>
          ))}
        </ul>
      </details>
    </Section>
  );
}

function Maintenance() {
  const store = useStore();
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<Record<string, unknown>>('/api/health').then(setHealth);
  }, []);
  return (
    <Section title="System">
      <div class="card space-y-3 text-sm">
        {health && (
          <ul class="grid grid-cols-2 gap-1">
            <li>OCR: {health.ocr ? '✓ on' : '✗ off'}</li>
            <li>PDF text: {health.pdf ? '✓' : '✗'}</li>
            <li>Meaning search: {health.semantic ? '✓ on' : '✗ off'}</li>
            <li>Model in memory: {health.model_loaded ? 'yes' : 'no (loads on use)'}</li>
            <li>Jobs waiting: {String(health.queue)}</li>
          </ul>
        )}
        {store.user.role === 'admin' && (
          <div>
            <button
              class="btn"
              disabled={busy}
              onClick={async () => {
                if (!confirm('Rebuild the search index from the receipts folder? Safe; takes a moment.')) return;
                setBusy(true);
                try {
                  const r = await api.post<{ receipts: number }>('/api/admin/reindex');
                  store.toast(`Rebuilt: ${r.receipts} receipts`);
                  store.bump();
                } catch (e) {
                  store.toast((e as Error).message, 'error');
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? <Spinner /> : <Icon name="refresh" size={16} />} Rebuild index from folder
            </button>
            <p class="muted mt-1 text-xs">The folder is the record; this re-reads every details file. Use it after copying receipts in by hand.</p>
          </div>
        )}
      </div>
    </Section>
  );
}
