import { useState } from 'preact/hooks';
import { api, type User } from '../api';
import { Field, Spinner } from '../components/ui';

export function Login(props: { setup: boolean; onUser: (u: User) => void }) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: Event) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = props.setup ? { username, display_name: displayName, password } : { username, password };
      const res = await api.post<{ user: User }>(props.setup ? '/api/auth/setup' : '/api/auth/login', body);
      props.onUser(res.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div class="flex min-h-dvh items-center justify-center p-4">
      <form class="card w-full max-w-sm space-y-4 p-6" onSubmit={submit}>
        <div class="flex items-center gap-3">
          <img src="/favicon.svg" alt="" class="h-10 w-10" />
          <div>
            <h1 class="text-xl font-semibold">Receipts</h1>
            <p class="muted text-sm">{props.setup ? 'Create the first account. It manages the household.' : 'Sign in'}</p>
          </div>
        </div>
        <Field label="Username">
          <input class="input" autoComplete="username" autoCapitalize="none" value={username} onInput={(e) => setUsername((e.target as HTMLInputElement).value)} required />
        </Field>
        {props.setup && (
          <Field label="Your name">
            <input class="input" value={displayName} onInput={(e) => setDisplayName((e.target as HTMLInputElement).value)} />
          </Field>
        )}
        <Field label="Password" hint={props.setup ? 'At least 8 characters' : undefined}>
          <input
            class="input"
            type="password"
            autoComplete={props.setup ? 'new-password' : 'current-password'}
            minLength={props.setup ? 8 : undefined}
            value={password}
            onInput={(e) => setPassword((e.target as HTMLInputElement).value)}
            required
          />
        </Field>
        {error && <p class="text-sm text-red-600">{error}</p>}
        <button class="btn btn-primary w-full" disabled={busy}>
          {busy && <Spinner />} {props.setup ? 'Create account' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
