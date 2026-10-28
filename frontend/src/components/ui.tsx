// Small shared pieces: icons, modal, chips, empty states.

import type { ComponentChildren } from 'preact';
import { useEffect } from 'preact/hooks';
import { categoryColor, tagColor, useStore } from '../store';

const paths: Record<string, string> = {
  home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  inbox: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z',
  chart: 'M3 3v18h18M7 15l4-4 3 3 5-6',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  camera: 'M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  x: 'M18 6 6 18M6 6l12 12',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35',
  filter: 'M22 3H2l8 9.46V19l4 2v-8.54z',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  image: 'M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6',
  bolt: 'M13 2 3 14h9l-1 8 10-12h-9z',
  check: 'M20 6 9 17l-5-5',
  chevron: 'm9 18 6-6-6-6',
  back: 'm15 18-6-6 6-6',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15',
  trash: 'M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2',
  paperclip: 'm21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48',
  sparkle: 'M12 3l1.9 5.8L20 10.7l-6.1 1.9L12 18.5l-1.9-5.9L4 10.7l6.1-1.9z',
  alert: 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
  plus: 'M12 5v14M5 12h14',
  zoom: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35M11 8v6M8 11h6',
};

export function Icon(props: { name: keyof typeof paths | string; class?: string; size?: number }) {
  const s = props.size ?? 20;
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class={props.class}
      aria-hidden="true"
    >
      <path d={paths[props.name] ?? ''} />
    </svg>
  );
}

export function Modal(props: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ComponentChildren;
  footer?: ComponentChildren;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!props.open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && props.onClose();
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [props.open]);
  if (!props.open) return null;
  return (
    <div class="fixed inset-0 z-40 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={props.onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={props.title}
        class={`flex max-h-[94dvh] w-full min-w-0 flex-col overflow-hidden rounded-t-2xl bg-white shadow-xl sm:rounded-2xl dark:bg-neutral-900 ${props.wide ? 'sm:max-w-4xl' : 'sm:max-w-lg'}`}
        onClick={(e) => e.stopPropagation()}
      >
        {props.title !== undefined && (
          <div class="flex items-center justify-between border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
            <h2 class="text-base font-semibold">{props.title}</h2>
            <button class="btn btn-ghost -mr-2 px-2" onClick={props.onClose} aria-label="Close">
              <Icon name="x" />
            </button>
          </div>
        )}
        <div class="flex-1 overflow-y-auto overscroll-contain">{props.children}</div>
        {props.footer && <div class="safe-bottom border-t border-neutral-200 px-4 py-3 dark:border-neutral-800">{props.footer}</div>}
      </div>
    </div>
  );
}

/** A category as a colored dot and its name: color as a hint, not a badge. */
export function CategoryChip(props: { name: string | null }) {
  const { categories } = useStore();
  if (!props.name) return null;
  return (
    <span class="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span class="h-2 w-2 shrink-0 rounded-full" style={{ background: categoryColor(categories, props.name) }} />
      {props.name}
    </span>
  );
}

export function TagChip(props: { name: string; note?: string; onRemove?: () => void }) {
  const { tags } = useStore();
  return (
    <span class="chip border-neutral-200 bg-neutral-100 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200">
      <span class="h-1.5 w-1.5 rounded-full" style={{ background: tagColor(tags, props.name) }} />
      {props.name}
      {props.note && <span class="font-normal text-red-700 dark:text-red-400">· {props.note}</span>}
      {props.onRemove && (
        <button onClick={props.onRemove} aria-label={`Remove ${props.name}`} class="-mr-1 rounded-full p-0.5 hover:bg-black/5">
          <Icon name="x" size={12} />
        </button>
      )}
    </span>
  );
}

export function Empty(props: { title: string; children?: ComponentChildren; icon?: string }) {
  return (
    <div class="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Icon name={props.icon ?? 'inbox'} size={28} class="text-neutral-400" />
      <p class="font-medium">{props.title}</p>
      {props.children && <div class="muted max-w-sm text-sm">{props.children}</div>}
    </div>
  );
}

export function Spinner(props: { class?: string }) {
  return <span class={`inline-block h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent ${props.class ?? ''}`} />;
}

export function Field(props: { label: string; children: ComponentChildren; class?: string; hint?: ComponentChildren }) {
  return (
    <label class={`block ${props.class ?? ''}`}>
      <span class="label">{props.label}</span>
      {props.children}
      {props.hint && <span class="muted mt-1 block text-xs">{props.hint}</span>}
    </label>
  );
}

export function Section(props: { title: string; action?: ComponentChildren; children: ComponentChildren }) {
  const { title, action, children } = props;
  return (
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-sm font-semibold text-neutral-600 dark:text-neutral-300">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Gray placeholder rows while a list loads. */
export function SkeletonRows(props: { n?: number }) {
  return (
    <div class="card divide-y divide-neutral-100 p-0 dark:divide-neutral-800" aria-busy="true" aria-label="Loading">
      {Array.from({ length: props.n ?? 5 }, (_, i) => (
        <div key={i} class="flex animate-pulse items-center gap-3 px-4 py-3.5">
          <div class="flex-1 space-y-2">
            <div class="h-3.5 w-2/5 rounded bg-neutral-200 dark:bg-neutral-800" />
            <div class="h-3 w-1/4 rounded bg-neutral-100 dark:bg-neutral-800/60" />
          </div>
          <div class="h-3.5 w-14 rounded bg-neutral-200 dark:bg-neutral-800" />
        </div>
      ))}
    </div>
  );
}
