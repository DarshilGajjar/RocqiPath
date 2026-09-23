# Studio

Studio is a local browser workspace for people who prefer not to write code.
It runs on your computer, reads slides where they are, and uses exactly the
same workflows as Python and the command line.

```console
python -m pip install -e ".[studio,extraction,orb,cellcount,viz]"
rocqipath studio                       # http://127.0.0.1:8765
rocqipath studio --workspace D:/StudioWork --port 8800
```

The workspace folder (default `~/RocqiPathStudio`) holds Studio's catalog and
every job's outputs. Slides are never copied or uploaded.

## Using it

- **Library.** "Add folder…" registers a folder of slides; subfolders are
  included. "Add synthetic demo slides" creates clearly labelled fake slides
  to try things out. Click slides to select them, in order.
- **Viewer.** Pan and zoom full-resolution slides. Choose a second slide to
  compare side by side; "Move both views together" keeps them in step. The
  panel below shows dimensions, objective and microns per pixel when the
  file records them.
- **Run workflow.** Pick a workflow, then its inputs (slides, folders or
  earlier results) and settings. The form is generated from the same config
  classes documented here, with the same help text. Rarely used settings
  sit under "Show advanced settings".
- **Jobs.** Jobs run one at a time in a separate process. Each shows its
  live log, results to preview or download, and a "Use as input…" button
  that starts another workflow on its output
  (see [Chaining](concepts/chaining.md)).

Workflows whose extra is not installed are marked "needs install".

## Safety

- **Local only:** Studio listens on `127.0.0.1` only and refuses requests
  from other origins.
- **Contained files:** browser requests name registered slides, folders or
  jobs, never arbitrary file paths. Downloads are limited to a job's own
  output folder.
- **Settings allowlist:** settings that name local files or pass raw
  arguments to a backend (for example `qc_output_dir` or `valis_kwargs`) are
  available in Python and the CLI but not accepted from the browser.

## API

The interface is a thin client for a small HTTP API; its interactive
reference is at <http://127.0.0.1:8765/docs> while Studio runs. The main
endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/workflows` | Every workflow with its generated settings schema |
| `POST /api/folders` | Register a folder `{"path": ...}` |
| `GET /api/slides`, `/api/slides/{id}/info`, `/tiles/{level}/{x}/{y}.jpg` | Catalog and Deep Zoom tiles |
| `POST /api/jobs` | `{"workflow", "inputs": [{"kind": "slide"\|"folder"\|"job", "id"}], "options", "settings"}` |
| `GET /api/jobs/{id}` | Status, log and artifacts |

## Developing the interface

See [`studio-web/README.md`](https://github.com/DarshilGajjar/RocqiPath/tree/main/studio-web).
The interface has no workflow-specific code, so new workflows appear
automatically.
