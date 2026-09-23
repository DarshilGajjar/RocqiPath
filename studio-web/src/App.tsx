import { Suspense, lazy, useCallback, useEffect, useState } from 'react';

import { api, type Folder, type InputRef, type Job, type Slide, type WorkflowInfo } from './api';
import { Jobs } from './components/Jobs';
import { Library } from './components/Library';
import { Run } from './components/Run';
import { ErrorNote, Spinner } from './components/ui';

// The viewer pulls in OpenSeadragon; load it only when opened.
const Viewer = lazy(() => import('./components/Viewer').then((module) => ({ default: module.Viewer })));

type View = 'library' | 'viewer' | 'run' | 'jobs';

const NAV: { view: View; label: string }[] = [
  { view: 'library', label: 'Library' },
  { view: 'viewer', label: 'Viewer' },
  { view: 'run', label: 'Run workflow' },
  { view: 'jobs', label: 'Jobs' },
];

export default function App() {
  const [view, setView] = useState<View>('library');
  const [status, setStatus] = useState<{ version: string; workspace: string } | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [slides, setSlides] = useState<Slide[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [viewing, setViewing] = useState<string[]>([]);
  const [workflow, setWorkflow] = useState<string | null>(null);
  const [runInputs, setRunInputs] = useState<InputRef[]>([]);
  const [runKey, setRunKey] = useState(0);
  const [job, setJob] = useState<string | null>(null);

  const refreshLibrary = useCallback(async () => {
    try {
      const [nextFolders, nextSlides] = await Promise.all([api.folders(), api.slides()]);
      setFolders(nextFolders);
      setSlides(nextSlides);
    } catch (exc) {
      setError((exc as Error).message);
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await api.jobs());
    } catch (exc) {
      setError((exc as Error).message);
    }
  }, []);

  useEffect(() => {
    api.status().then(setStatus).catch((exc: Error) => setError(`Cannot reach the Studio server: ${exc.message}`));
    api.workflows().then(setWorkflows).catch((exc: Error) => setError(exc.message));
    void refreshLibrary();
    void refreshJobs();
  }, [refreshLibrary, refreshJobs]);

  useEffect(() => {
    if (!jobs.some((j) => j.status === 'queued' || j.status === 'running')) return;
    const timer = window.setInterval(refreshJobs, 2000);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  function startRun(inputs: InputRef[]) {
    setRunInputs(inputs);
    setRunKey((key) => key + 1);
    setView('run');
  }

  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <aside className="bg-nav text-nav-ink md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0">
        <div className="flex items-center justify-between px-5 py-4 md:block md:py-6">
          <p className="font-serif text-xl">
            RocqiPath <span className="text-[#c98ab7]">Studio</span>
          </p>
          <p className="hidden text-xs text-nav-ink/60 md:mt-1 md:block">Local pathology workspace</p>
        </div>
        <nav aria-label="Main">
          <ul className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
            {NAV.map((item) => (
              <li key={item.view}>
                <button
                  type="button"
                  onClick={() => setView(item.view)}
                  aria-current={view === item.view ? 'page' : undefined}
                  className={`w-full whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                    view === item.view ? 'bg-white/10 text-white' : 'text-nav-ink/75 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  {item.label}
                  {item.view === 'jobs' && jobs.some((j) => j.status === 'running') && (
                    <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-[#c98ab7]" aria-label="running" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        {status && (
          <p className="hidden break-all px-5 pt-8 text-[11px] leading-relaxed text-nav-ink/50 md:block">
            v{status.version}
            <br />
            {status.workspace}
          </p>
        )}
      </aside>

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-6xl">
          {error && (
            <div className="mb-4">
              <ErrorNote message={error} />
            </div>
          )}
          {view === 'library' && (
            <Library
              folders={folders}
              slides={slides}
              selected={selected}
              onToggle={(id) =>
                setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]))
              }
              onClearSelection={() => setSelected([])}
              onChanged={refreshLibrary}
              onView={(ids) => {
                setViewing(ids);
                setView('viewer');
              }}
              onRun={(ids) => startRun(ids.map((id) => ({ kind: 'slide', id })))}
            />
          )}
          {view === 'viewer' && (
            <Suspense fallback={<Spinner label="Loading viewer" />}>
              <Viewer slides={slides} ids={viewing} onChoose={setViewing} />
            </Suspense>
          )}
          {view === 'run' && (
            <Run
              key={runKey}
              workflows={workflows}
              chosen={workflow}
              onChoose={setWorkflow}
              sources={{ slides, folders, jobs }}
              initialInputs={runInputs}
              onSubmitted={(submitted) => {
                setJob(submitted.id);
                void refreshJobs();
                setView('jobs');
              }}
            />
          )}
          {view === 'jobs' && (
            <Jobs
              jobs={jobs}
              selected={job}
              onSelect={setJob}
              onChanged={refreshJobs}
              onUseAsInput={(finished) => startRun([{ kind: 'job', id: finished.id }])}
            />
          )}
        </div>
      </main>
    </div>
  );
}
