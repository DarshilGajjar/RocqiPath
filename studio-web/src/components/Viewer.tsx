import OpenSeadragon from 'openseadragon';
import { useEffect, useRef, useState } from 'react';

import { api, type Slide, type SlideInfo } from '../api';
import { Button, Empty, ErrorNote, PageHeader, Spinner } from './ui';

interface ViewerProps {
  slides: Slide[];
  ids: string[];
  onChoose: (ids: string[]) => void;
}

export function Viewer({ slides, ids, onChoose }: ViewerProps) {
  const [synced, setSynced] = useState(true);
  const viewers = useRef<(OpenSeadragon.Viewer | null)[]>([]);
  const shown = ids.filter((id) => slides.some((slide) => slide.id === id)).slice(0, 2);

  useEffect(() => {
    if (!synced || shown.length < 2) return;
    const [left, right] = viewers.current;
    if (!left || !right) return;
    let syncing = false;
    const follow = (source: OpenSeadragon.Viewer, target: OpenSeadragon.Viewer) => () => {
      if (syncing) return;
      syncing = true;
      target.viewport.zoomTo(source.viewport.getZoom());
      target.viewport.panTo(source.viewport.getCenter());
      syncing = false;
    };
    const leftHandler = follow(left, right);
    const rightHandler = follow(right, left);
    left.addHandler('viewport-change', leftHandler);
    right.addHandler('viewport-change', rightHandler);
    return () => {
      left.removeHandler('viewport-change', leftHandler);
      right.removeHandler('viewport-change', rightHandler);
    };
  }, [synced, shown.join()]);

  return (
    <div>
      <PageHeader
        title="Viewer"
        lead="Pan and zoom full-resolution slides. Pick a second slide to compare side by side."
        actions={
          shown.length === 2 && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={synced} onChange={(e) => setSynced(e.target.checked)} />
              Move both views together
            </label>
          )
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        {[0, 1].map((pane) => (
          <label key={pane} className="flex items-center gap-2 text-sm">
            <span className="text-muted">{pane === 0 ? 'Slide' : 'Compare with'}</span>
            <select
              value={shown[pane] ?? ''}
              onChange={(event) => {
                const next = [...shown];
                if (event.target.value) next[pane] = event.target.value;
                else next.splice(pane, 1);
                onChoose(next.filter(Boolean));
              }}
              className="max-w-64 rounded-lg border border-line bg-panel px-2 py-1.5"
              disabled={pane === 1 && shown.length === 0}
            >
              <option value="">{pane === 0 ? 'Choose a slide' : 'None'}</option>
              {slides.map((slide) => (
                <option key={slide.id} value={slide.id}>
                  {slide.name}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {shown.length === 0 ? (
        <Empty title="Choose a slide to view">Select slides in the library, or choose one above.</Empty>
      ) : (
        <div className={`grid gap-4 ${shown.length === 2 ? 'lg:grid-cols-2' : ''}`}>
          {shown.map((id, index) => (
            <SlidePane
              key={id}
              slide={slides.find((slide) => slide.id === id)!}
              onReady={(viewer) => {
                viewers.current[index] = viewer;
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SlidePane({ slide, onReady }: { slide: Slide; onReady: (viewer: OpenSeadragon.Viewer | null) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<OpenSeadragon.Viewer | null>(null);
  const [info, setInfo] = useState<SlideInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setInfo(null);
    setError(null);
    api
      .slideInfo(slide.id)
      .then((result) => !cancelled && setInfo(result))
      .catch((exc: Error) => !cancelled && setError(exc.message));
    return () => {
      cancelled = true;
    };
  }, [slide.id]);

  useEffect(() => {
    if (!info || !container.current) return;
    const instance = OpenSeadragon({
      element: container.current,
      showNavigationControl: false,
      showNavigator: true,
      navigatorPosition: 'BOTTOM_RIGHT',
      maxZoomPixelRatio: 2,
      visibilityRatio: 0.5,
      tileSources: {
        width: info.width,
        height: info.height,
        tileSize: info.tile_size,
        tileOverlap: 0,
        minLevel: 0,
        maxLevel: info.max_level,
        getTileUrl: (level: number, x: number, y: number) => api.tileUrl(slide.id, level, x, y),
      },
    });
    viewer.current = instance;
    onReady(instance);
    return () => {
      onReady(null);
      instance.destroy();
      viewer.current = null;
    };
  }, [info, slide.id]);

  const zoom = (factor: number) => viewer.current?.viewport.zoomBy(factor).applyConstraints();

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-panel">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <span className="truncate font-medium" title={slide.path}>
          {slide.name}
        </span>
        <span className="flex gap-1">
          <Button tone="ghost" aria-label="Zoom in" onClick={() => zoom(1.5)}>
            +
          </Button>
          <Button tone="ghost" aria-label="Zoom out" onClick={() => zoom(1 / 1.5)}>
            −
          </Button>
          <Button tone="ghost" onClick={() => viewer.current?.viewport.goHome()}>
            Reset
          </Button>
        </span>
      </figcaption>
      <div className="relative h-[62vh] min-h-80 bg-canvas">
        {!info && !error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Spinner label="Opening slide" />
          </div>
        )}
        {error && (
          <div className="p-4">
            <ErrorNote message={error} />
          </div>
        )}
        <div ref={container} className="absolute inset-0" />
      </div>
      {info && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 px-4 py-3 text-xs sm:grid-cols-4">
          <Meta label="Dimensions" value={`${info.width.toLocaleString()} × ${info.height.toLocaleString()} px`} />
          <Meta label="Objective" value={info.objective ? `${info.objective}×` : 'Unknown — set source magnification'} />
          <Meta label="Microns / pixel" value={info.mpp ?? 'Unknown'} />
          <Meta label="Reader" value={`${info.backend}, ${info.levels} level${info.levels === 1 ? '' : 's'}`} />
        </dl>
      )}
    </figure>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
