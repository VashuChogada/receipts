// The backend's API. Every write carries X-Requested-With, which the server
// requires (main.py, Guard) so another site's form can't post here.

export type Status = 'queued' | 'processing' | 'review' | 'confirmed' | 'failed';

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: 'admin' | 'member';
  disabled?: number;
}

/** The server's settings the UI needs, from /api/auth/state. */
export interface ServerInfo {
  currency: string;
}

export interface AuthState {
  needs_setup: boolean;
  user: User | null;
  server?: ServerInfo;
}

export const server: ServerInfo = { currency: 'USD' };

export interface LineItem {
  description: string;
  qty?: number | null;
  unit_price?: number | null;
  amount?: number | null;
}

export interface Hsa {
  patient?: string | null;
  provider?: string | null;
  eligible_amount?: number | null;
  reimbursed?: boolean;
  reimbursed_date?: string | null;
  claim_ref?: string | null;
}

export interface Donation {
  organization?: string | null;
  ein?: string | null;
  donation_type?: 'cash' | 'noncash' | null;
  deductible_amount?: number | null;
  items_description?: string | null;
  acknowledgment?: boolean;
}

export interface Warranty {
  product?: string | null;
  serial?: string | null;
  expires_on?: string | null;
}

export interface Attachment {
  id: string;
  file_path: string;
  mime: string;
  original_name: string | null;
  label: string | null;
  created_at: string;
}

export interface HistoryEntry {
  at: string;
  by: string | null;
  changes: Record<string, [unknown, unknown]>;
}

export interface ReceiptSummary {
  id: string;
  status: Status;
  merchant: string | null;
  txn_date: string | null;
  txn_time: string | null;
  total: number | null;
  tax: number | null;
  category: string | null;
  payment_method: string | null;
  card_last4: string | null;
  tags: string[];
  mime: string;
  created_by: string | null;
  created_at: string;
  needs_acknowledgment: boolean;
  ocr_confidence: number | null;
  error: string | null;
  reimbursed?: boolean;
}

export interface Receipt extends ReceiptSummary {
  merchant_raw: string | null;
  subtotal: number | null;
  notes: string | null;
  file_path: string;
  sidecar_path: string;
  original_name: string | null;
  raw_text: string | null;
  parsed: Record<string, unknown> | null;
  suggested_tags: string[];
  hsa: Hsa | null;
  donation: Donation | null;
  warranty: Warranty | null;
  line_items: LineItem[];
  attachments: Attachment[];
  history: HistoryEntry[];
  kinds: string[];
  updated_at: string;
  confirmed_at: string | null;
}

export interface Chip {
  key: string;
  label: string;
}

export interface Summary {
  count: number;
  total: number;
  tax: number;
  by_category: { name: string; count: number; total: number }[];
}

export interface SearchResult {
  items: ReceiptSummary[];
  total: number;
  summary: Summary;
  search: Record<string, number | boolean>;
  query: { chips: Chip[]; text: string; filters: Record<string, unknown> };
}

export interface Category {
  name: string;
  color: string;
  sort: number;
  count: number;
}

export interface Tag {
  name: string;
  kind: 'plain' | 'hsa' | 'donation' | 'warranty';
  color: string;
  count: number;
}

export interface Rule {
  id: number;
  pattern: string;
  field: 'merchant' | 'text';
  is_regex: boolean;
  category: string | null;
  tag: string | null;
  priority: number;
  source: 'default' | 'user';
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg ?? message;
    } catch {
      /* not JSON */
    }
    if (res.status === 401) window.dispatchEvent(new CustomEvent('signed-out'));
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
};

/** Upload with progress, which fetch can't report. */
export function uploadFiles(files: Blob[], names: string[], onProgress?: (fraction: number) => void, tags: string[] = []) {
  return new Promise<{ receipts: { id: string; status: Status }[] }>((resolve, reject) => {
    const form = new FormData();
    files.forEach((f, i) => form.append('files', f, names[i]));
    tags.forEach((t) => form.append('tags', t));
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/receipts');
    xhr.setRequestHeader('X-Requested-With', 'fetch');
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        let msg = xhr.statusText;
        try {
          msg = JSON.parse(xhr.responseText).detail ?? msg;
        } catch {
          /* not JSON */
        }
        reject(new ApiError(xhr.status, msg));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, 'Network error: is the server reachable?'));
    xhr.send(form);
  });
}

/** Query string from a filter object; arrays repeat the key, empty values drop. */
export function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const previewUrl = (r: { id: string; file_path?: string; updated_at?: string }, w = 320) =>
  `/api/receipts/${r.id}/preview?w=${w}&v=${encodeURIComponent(r.updated_at ?? r.file_path ?? '')}`;
