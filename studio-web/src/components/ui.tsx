import type { ButtonHTMLAttributes, ReactNode } from 'react';

import type { JobStatus } from '../api';

type Tone = 'primary' | 'secondary' | 'ghost' | 'danger';

const tones: Record<Tone, string> = {
  primary: 'bg-plum text-white hover:bg-plum-strong disabled:bg-plum/40',
  secondary: 'border border-line bg-panel text-ink hover:border-plum/50 hover:text-plum disabled:opacity-50',
  ghost: 'text-muted hover:bg-plum-soft hover:text-plum disabled:opacity-50',
  danger: 'border border-bad/30 bg-panel text-bad hover:bg-bad/5 disabled:opacity-50',
};

export function Button({
  tone = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${tones[tone]} ${className}`}
      {...props}
    />
  );
}

export function PageHeader({ title, lead, actions }: { title: string; lead?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div className="max-w-2xl">
        <h1 className="font-serif text-3xl tracking-tight">{title}</h1>
        {lead && <p className="mt-1.5 text-sm text-muted">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-panel p-5 ${className}`}>{children}</section>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-12 text-center">
      <p className="font-serif text-lg">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad">
      {message}
    </p>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" role="status">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-plum" />
      {label}
    </span>
  );
}

const statusTone: Record<JobStatus, string> = {
  queued: 'bg-line text-muted',
  running: 'bg-plum-soft text-plum',
  succeeded: 'bg-ok/10 text-ok',
  failed: 'bg-bad/10 text-bad',
  cancelled: 'bg-warn/10 text-warn',
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusTone[status]}`}>
      {status}
    </span>
  );
}

export function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
