import type { InputRef, Job, WorkflowInfo } from '../api';
import { plain } from '../settings';
import { Empty, PageHeader, Spinner } from './ui';
import { WorkflowForm, type Sources } from './WorkflowForm';

interface RunProps {
  workflows: WorkflowInfo[] | null;
  chosen: string | null;
  onChoose: (name: string) => void;
  sources: Sources;
  initialInputs: InputRef[];
  onSubmitted: (job: Job) => void;
}

export function Run({ workflows, chosen, onChoose, sources, initialInputs, onSubmitted }: RunProps) {
  if (!workflows) return <Spinner label="Loading workflows" />;
  const workflow = workflows.find((w) => w.name === chosen) ?? null;
  return (
    <div>
      <PageHeader
        title="Run a workflow"
        lead="Every workflow here is the same function you can call from Python or the command line."
      />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <nav aria-label="Workflows">
          <ul className="space-y-1">
            {workflows.map((w) => (
              <li key={w.name}>
                <button
                  type="button"
                  onClick={() => onChoose(w.name)}
                  aria-current={w.name === chosen ? 'page' : undefined}
                  className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                    w.name === chosen ? 'bg-plum-soft text-plum' : 'hover:bg-panel'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2 text-sm font-medium">
                    {w.label}
                    {!w.available && <span className="text-[10px] uppercase tracking-wide text-warn">needs install</span>}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted">{plain(w.summary)}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <section className="min-w-0 rounded-xl border border-line bg-panel p-5">
          {workflow ? (
            <>
              <h2 className="font-serif text-2xl">{workflow.label}</h2>
              <p className="mb-5 mt-1 text-sm text-muted">{plain(workflow.summary)}</p>
              <WorkflowForm
                key={workflow.name}
                workflow={workflow}
                sources={sources}
                initialInputs={initialInputs}
                onSubmitted={onSubmitted}
              />
            </>
          ) : (
            <Empty title="Choose a workflow">
              Pick one on the left. Selected slides and earlier results can be used as inputs.
            </Empty>
          )}
        </section>
      </div>
    </div>
  );
}
