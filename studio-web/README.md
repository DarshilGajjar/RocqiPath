# RocqiPath Studio interface

The browser interface for `rocqipath studio`: a slide library, a zoomable
side-by-side viewer, one generated form per workflow, and job history with
logs and results. It is a static React app; the production build is written to
`src/rocqipath/studio/static/` and served by the Python server, so **using**
Studio needs no Node.js:

```console
python -m pip install -e ".[studio,extraction,cellcount]"
rocqipath studio            # then open http://127.0.0.1:8765
```

## Developing the interface

Requires Node.js 20+ and pnpm.

```console
pnpm install
bash ../start-studio.sh --dev   # Python API on :8765 and Vite on :5173 with live reload
pnpm test                       # unit tests (form generation, settings parsing)
pnpm build                      # type-check and rebuild src/rocqipath/studio/static
```

Commit the rebuilt `static/` folder together with interface changes.

## How the forms are generated

The interface has no per-workflow code. `GET /api/workflows` returns each
workflow's settings schema, built from its config class and docstrings, and
`src/components/WorkflowForm.tsx` renders any schema. A new workflow registered
in Python appears here automatically.

`src/test/workflows.json` is a snapshot of that endpoint used by the tests.
After changing a config, regenerate it (a Python test fails until you do):

```console
python -m rocqipath.studio.catalog > studio-web/src/test/workflows.json
```

## Layout

| Path | Purpose |
|---|---|
| `src/api.ts` | Typed client for the Studio API |
| `src/settings.ts` | Schema to form fields to submitted settings |
| `src/components/Library.tsx` | Folders, folder browser, slide grid and selection |
| `src/components/Viewer.tsx` | OpenSeadragon viewer with synchronized comparison |
| `src/components/WorkflowForm.tsx` | The generic workflow form and input pickers |
| `src/components/Run.tsx` | Workflow list and form |
| `src/components/Jobs.tsx` | Job history, live log, artifacts, "use as input" |
