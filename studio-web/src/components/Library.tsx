import { useEffect, useState } from 'react';

import { api, type Folder, type Slide } from '../api';
import { Button, Empty, ErrorNote, PageHeader, Spinner, formatBytes } from './ui';

interface LibraryProps {
  folders: Folder[];
  slides: Slide[];
  selected: string[];
  onToggle: (id: string) => void;
  onClearSelection: () => void;
  onChanged: () => void;
  onView: (ids: string[]) => void;
  onRun: (ids: string[]) => void;
}

export function Library({
  folders,
  slides,
  selected,
  onToggle,
  onClearSelection,
  onChanged,
  onView,
  onRun,
}: LibraryProps) {
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadDemo() {
    setBusy(true);
    setError(null);
    try {
      await api.demo();
      onChanged();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Slide library"
        lead="Slides are read in place from folders you add. Nothing is uploaded or copied."
        actions={
          <>
            <Button onClick={loadDemo} disabled={busy}>
              Add synthetic demo slides
            </Button>
            <Button tone="primary" onClick={() => setBrowsing(true)}>
              Add folder…
            </Button>
          </>
        }
      />
      <ErrorNote message={error} />
      {browsing && (
        <FolderBrowser
          onClose={() => setBrowsing(false)}
          onAdded={() => {
            setBrowsing(false);
            onChanged();
          }}
        />
      )}

      {folders.length > 0 && (
        <ul className="mb-6 flex flex-wrap gap-2 text-xs text-muted" aria-label="Registered folders">
          {folders.map((folder) => (
            <li key={folder.id} className="rounded-full border border-line bg-panel px-3 py-1" title={folder.path}>
              {folder.name} · {folder.count} image{folder.count === 1 ? '' : 's'}
              {folder.demo && ' · synthetic'}
              {folder.truncated && ' · first 2,000 shown'}
            </li>
          ))}
        </ul>
      )}

      {selected.length > 0 && (
        <div className="sticky top-0 z-10 mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-plum/30 bg-plum-soft px-4 py-2.5 text-sm">
          <span className="font-medium text-plum">{selected.length} selected</span>
          <Button tone="secondary" onClick={() => onView(selected.slice(0, 2))} disabled={selected.length > 2}>
            {selected.length === 2 ? 'Compare in viewer' : 'Open in viewer'}
          </Button>
          <Button tone="primary" onClick={() => onRun(selected)}>
            Use in a workflow
          </Button>
          <Button tone="ghost" onClick={onClearSelection}>
            Clear
          </Button>
        </div>
      )}

      {slides.length === 0 ? (
        <Empty title="No slides yet">
          Add a folder containing whole-slide images (.svs, .ndpi, .tif, …) or ordinary images.
          Demo slides are clearly marked as synthetic.
        </Empty>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-4">
          {slides.map((slide) => {
            const position = selected.indexOf(slide.id);
            return (
              <li key={slide.id}>
                <button
                  type="button"
                  onClick={() => onToggle(slide.id)}
                  onDoubleClick={() => onView([slide.id])}
                  aria-pressed={position >= 0}
                  className={`group w-full overflow-hidden rounded-xl border bg-panel text-left transition-shadow hover:shadow-md ${
                    position >= 0 ? 'border-plum ring-2 ring-plum/30' : 'border-line'
                  }`}
                >
                  <div className="relative aspect-[4/3] bg-canvas">
                    <img
                      src={api.thumbnailUrl(slide.id)}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-contain"
                    />
                    {position >= 0 && (
                      <span className="absolute left-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-plum text-xs font-semibold text-white">
                        {position + 1}
                      </span>
                    )}
                    {slide.demo && (
                      <span className="absolute right-2 top-2 rounded bg-ink/70 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white">
                        Synthetic
                      </span>
                    )}
                  </div>
                  <div className="px-3 py-2.5">
                    <p className="truncate text-sm font-medium" title={slide.relative}>
                      {slide.name}
                    </p>
                    <p className="text-xs text-muted">
                      {slide.format} · {formatBytes(slide.size)}
                    </p>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function FolderBrowser({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [listing, setListing] = useState<Awaited<ReturnType<typeof api.browse>> | null>(null);
  const [typed, setTyped] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function open(path?: string) {
    setError(null);
    try {
      const result = await api.browse(path);
      setListing(result);
      setTyped(result.path);
    } catch (exc) {
      setError((exc as Error).message);
    }
  }

  useEffect(() => {
    void open();
  }, []);

  async function add() {
    setAdding(true);
    setError(null);
    try {
      await api.addFolder(typed);
      onAdded();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setAdding(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Add a folder" className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-panel p-5 shadow-xl">
        <h2 className="font-serif text-xl">Add a folder of slides</h2>
        <p className="mt-1 text-sm text-muted">Images in the folder and its subfolders are listed.</p>
        <form
          className="mt-4 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void open(typed);
          }}
        >
          <label className="sr-only" htmlFor="folder-path">
            Folder path
          </label>
          <input
            id="folder-path"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-1.5 font-mono text-sm"
          />
          <Button type="submit">Go</Button>
        </form>
        <div className="mt-3 min-h-40 flex-1 overflow-auto rounded-lg border border-line">
          {!listing ? (
            <div className="p-4">
              <Spinner />
            </div>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {listing.parent !== listing.path && (
                <li>
                  <button type="button" className="w-full px-3 py-2 text-left text-muted hover:bg-plum-soft" onClick={() => open(listing.parent)}>
                    ↑ Parent folder
                  </button>
                </li>
              )}
              {listing.directories.map((directory) => (
                <li key={directory.path}>
                  <button type="button" className="w-full px-3 py-2 text-left hover:bg-plum-soft" onClick={() => open(directory.path)}>
                    {directory.name}
                  </button>
                </li>
              ))}
              {listing.directories.length === 0 && <li className="px-3 py-2 text-muted">No subfolders.</li>}
            </ul>
          )}
        </div>
        <div className="mt-3">
          <ErrorNote message={error} />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button tone="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button tone="primary" onClick={add} disabled={adding || !typed}>
            {adding ? 'Adding…' : 'Add this folder'}
          </Button>
        </div>
      </div>
    </div>
  );
}
