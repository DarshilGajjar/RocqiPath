import { useEffect, useRef, useState } from 'react';

import { api, type Job, type JobDetail } from '../api';
import { labelOf } from '../settings';
import { Button, Empty, ErrorNote, PageHeader, Spinner, StatusBadge, formatBytes, formatTime } from './ui';

interface JobsProps {
  jobs: Job[];
  selected: string | null;
  onSelect: (id: string) => void;
  onUseAsInput: (job: Job) => void;
  onChanged: () => void;
}

const ACTIVE = new Set(['queued', 'running']);
const IMAGE = /\.(png|jpe?g)$/i;

export function Jobs({ jobs, selected, onSelect, onUseAsInput, onChanged }: JobsProps) {
  const current = jobs.find((job) => job.id === selected) ?? jobs[0];
  return (
    <div>
      <PageHeader title="Jobs" lead="One job runs at a time in a separate process; outputs stay in the Studio workspace." />
      {jobs.length === 0 ? (
        <Empty title="No jobs yet">Run a workflow and its progress, log and results appear here.</Empty>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <ul className="space-y-1" aria-label="Job history">
            {jobs.map((job) => (
              <li key={job.id}>
                <button
                  type="button"
                  onClick={() => onSelect(job.id)}
                  aria-current={job.id === current?.id ? 'true' : undefined}
                  className={`w-full rounded-lg px-3 py-2 text-left ${job.id === current?.id ? 'bg-plum-soft' : 'hover:bg-panel'}`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{labelOf(job.workflow)}</span>
                    <StatusBadge status={job.status} />
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted">
                    {formatTime(job.created)} · {job.inputs.join(', ')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {current && <JobPanel key={current.id} job={current} onUseAsInput={onUseAsInput} onChanged={onChanged} />}
        </div>
      )}
    </div>
  );
}

function JobPanel({ job, onUseAsInput, onChanged }: { job: Job; onUseAsInput: (job: Job) => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const log = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        const next = await api.job(job.id);
        if (cancelled) return;
        setDetail(next);
        if (ACTIVE.has(next.status)) timer = window.setTimeout(load, 1500);
        else if (ACTIVE.has(job.status)) onChanged();
      } catch (exc) {
        if (!cancelled) setError((exc as Error).message);
      }
    };
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [job.id]);

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [detail?.log]);

  if (error) return <ErrorNote message={error} />;
  if (!detail) return <Spinner />;

  return (
    <section className="min-w-0 space-y-4 rounded-xl border border-line bg-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-2xl">{labelOf(detail.workflow)}</h2>
          <p className="text-xs text-muted">
            Started {formatTime(detail.started)} · finished {formatTime(detail.finished)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={detail.status} />
          {ACTIVE.has(detail.status) && (
            <Button tone="danger" onClick={() => api.cancel(detail.id).then(onChanged)}>
              Cancel
            </Button>
          )}
          {detail.status === 'succeeded' && (
            <Button tone="primary" onClick={() => onUseAsInput(detail)}>
              Use as input…
            </Button>
          )}
        </div>
      </div>
      <ErrorNote message={detail.error} />

      <div>
        <h3 className="mb-2 text-sm font-semibold text-muted">Log</h3>
        <pre ref={log} className="max-h-72 overflow-auto rounded-lg bg-nav p-3 font-mono text-xs leading-relaxed text-nav-ink">
          {detail.log || 'No output yet.'}
        </pre>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-muted">Results ({detail.artifacts.length})</h3>
        {detail.artifacts.length === 0 ? (
          <p className="text-sm text-muted">{ACTIVE.has(detail.status) ? 'Results appear as they are written.' : 'No files were written.'}</p>
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line text-sm">
            {detail.artifacts.map((artifact) => (
              <li key={artifact.path} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0 truncate font-mono text-xs" title={artifact.path}>
                  {artifact.path}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                  {formatBytes(artifact.size)}
                  {IMAGE.test(artifact.name) && (
                    <Button tone="ghost" onClick={() => setPreview(artifact.path)}>
                      Preview
                    </Button>
                  )}
                  <a className="rounded-lg px-2 py-1 text-plum hover:bg-plum-soft" href={api.artifactUrl(detail.id, artifact.path)} download>
                    Download
                  </a>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {preview && (
        <figure className="rounded-lg border border-line p-2">
          <img src={api.artifactUrl(detail.id, preview)} alt={preview} className="mx-auto max-h-[60vh]" />
          <figcaption className="mt-2 flex justify-between text-xs text-muted">
            {preview}
            <Button tone="ghost" onClick={() => setPreview(null)}>
              Close
            </Button>
          </figcaption>
        </figure>
      )}
    </section>
  );
}
