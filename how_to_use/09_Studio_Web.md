# Using RocqiPath Studio locally

## Current status

Studio is **under development**. The local API, slide catalog, tiled-image
endpoints, workflow adapters, and background-job code have been written, but
their integration tests have not yet passed verification. `studio-web` still
contains the generated interface scaffold; the slide library, viewer controls,
and workflow forms are not connected yet.

This guide distinguishes the current developer/API entry points from the
planned browser experience. It does not imply that the complete Studio app is
ready to use. The existing RocqiPath notebooks remain the established way to
run the library while Studio is being completed.

## Requirements

- 64-bit Python **3.10 or 3.11** for the RocqiPath backend.
- Node.js **22.13 or newer** and pnpm for frontend development.
- Local slide files and a writable folder for Studio's catalog and results.
- OpenSlide and libvips for workflows that require those native libraries.

The Python API and frontend development server are separate processes. Starting
the frontend alone does not start RocqiPath or connect the unfinished interface
to the processing service.

## 1. Prepare the Python environment

Run these commands from the **RocqiPath repository root**. For a new Windows
environment with Python 3.11 installed:

```powershell
py -3.11 -m venv .venv-studio
.\.venv-studio\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[extraction,orb,cellcount,viz]"
python -m pip install fastapi uvicorn
```

If you already have a working RocqiPath environment, activate that environment
and install `fastapi` and `uvicorn` there instead. The current `pyproject.toml`
does **not** yet define a `studio` extra, so use the explicit installation
commands above rather than `pip install rocqipath[studio]`.

Install additional processing backends only when needed:

```powershell
# Stain normalization
python -m pip install -e ".[stain]"

# Non-rigid VALIS alignment
python -m pip install -e ".[valis]"

# Semantic tissue detection
python -m pip install -e ".[extraction,semantic]"
```

Installing Python packages does not necessarily install OpenSlide or libvips.
The `/api/status` response reports missing packages and detected native-load
failures. Model-backed workflows may also need model weights and additional
runtime setup; package detection is not a successful inference test.

## 2. Start the local backend

From the repository root, in the activated environment:

```powershell
python -m rocqipath.studio --workspace "C:\RocqiPathStudio" --port 8765
```

Replace the workspace path with a writable local directory. If omitted, the
default is `RocqiPathStudio` in your user home directory. The server binds to
`127.0.0.1`; it is intended for this computer, not a shared lab server.

Keep this terminal open. In a browser, inspect:

- [Backend status](http://127.0.0.1:8765/api/status)
- [Interactive API reference](http://127.0.0.1:8765/docs)

The root [Studio address](http://127.0.0.1:8765/) may return `404` at this stage:
the launcher serves the website only when a built static interface is present.
This does not by itself mean the API failed to start.

Press **Ctrl+C** in the server terminal to stop Studio. Closing a browser tab
does not stop the server or its background jobs.

## 3. Run the current frontend scaffold

Open a second terminal from the repository root:

```powershell
cd studio-web
pnpm install
```

After installing dependencies, use the single startup script from the repository
root in **Git Bash** on Windows, or Bash on macOS/Linux:

```bash
bash start-studio.sh
```

It starts the frontend development server and forwards optional arguments
(`bash start-studio.sh --port 3001`). It does not install dependencies or start
the Python API. Keep the backend terminal from step 2 running separately.
Press **Ctrl+C** to stop the frontend. From inside `studio-web`, the equivalent
command is `bash ../start-studio.sh`.

Open the local address printed by the development server. Currently this is a
starter preview, **not the finished pathology workspace**. Do not expect slide
import or processing buttons to work before the UI integration is completed.

Other existing scripts:

```powershell
pnpm build
pnpm lint
```

The generated `pnpm start` command runs Wrangler. It is not the Python Studio
launcher and should not be used as the final local-app startup command. The
static build configuration and its connection to FastAPI remain unfinished.

If pnpm reports ignored dependency build scripts, review the named packages
using its approval workflow. Do not disable dependency policies globally to
make installation appear successful.

## 4. Explore the backend through PowerShell

These examples correspond to the current API implementation; they still need
integration verification. Run them in another terminal while the backend is
running. They use explicit JSON requests, as required for local mutations.

### Register a slide folder

```powershell
$studioUrl = "http://127.0.0.1:8765"
$folderBody = @{ path = "C:\Path\To\Your\Slides" } | ConvertTo-Json
Invoke-RestMethod "$studioUrl/api/folders" -Method Post `
    -ContentType "application/json" -Body $folderBody

$studioSlides = @(Invoke-RestMethod "$studioUrl/api/slides")
$studioSlides | Select-Object id, name, format, size, demo
```

Replace the example path before running it. Registration references images in
place; it does not upload or copy original slides. Keep the source folder
available while jobs run.

Scanning is recursive, excludes hidden folders and common dependency folders,
and registers at most **2,000 images per scan**. Check the returned `truncated`
field. Recognized extensions are TIFF, SVS, NDPI, SCN, MRXS, PNG, and JPEG;
recognizing an extension does not guarantee the available reader supports it.

### Create demonstration slides instead

```powershell
Invoke-RestMethod "$studioUrl/api/demo" -Method Post `
    -ContentType "application/json" -Body '{}'
$studioSlides = @(Invoke-RestMethod "$studioUrl/api/slides")
```

This generates three explicitly labelled synthetic images in the Studio
workspace. They are for exploring software behavior, not evaluating pathology
accuracy. They have no scanner objective metadata; a processing experiment
must supply an explicit source magnification.

### Inspect a selected image

```powershell
$studioSlide = $studioSlides | Select-Object -First 1
if ($null -eq $studioSlide) { throw "Register a folder containing images first." }

Invoke-RestMethod "$studioUrl/api/slides/$($studioSlide.id)/info"
```

Metadata includes dimensions, available objective power/MPP, the reader backend,
and tile levels. Missing magnification is not automatically assigned a scanner
value. A thumbnail is available at:

```text
http://127.0.0.1:8765/api/slides/<slide-id>/thumbnail
```

### Submit a cell-count job

Choose the intended slide explicitly from `$studioSlides` before submitting.
Replace the example magnifications with values appropriate to that image.

```powershell
$jobBody = @{
    workflow = "count"
    slide_ids = @($studioSlide.id)
    parameters = @{
        source_magnification = 20
        target_magnification = 20
        patch_size = 512
        min_cell_area = 50
        tissue_threshold = 0.1
    }
} | ConvertTo-Json -Depth 5

$studioJob = Invoke-RestMethod "$studioUrl/api/jobs" -Method Post `
    -ContentType "application/json" -Body $jobBody

Invoke-RestMethod "$studioUrl/api/jobs/$($studioJob.id)"
```

One job runs at a time. Subsequent jobs stay queued. The job response includes
its status; detailed responses include logs, errors, the output directory, and
artifact names. Running indicates activity, not a measured percentage complete.

### Read results or cancel a job

```powershell
$jobDetails = Invoke-RestMethod "$studioUrl/api/jobs/$($studioJob.id)"
$jobDetails | Select-Object status, error, output_dir
$jobDetails.log
$jobDetails.artifacts | Select-Object name, path, size

# Run only if you want to stop this queued or running job:
Invoke-RestMethod "$studioUrl/api/jobs/$($studioJob.id)/cancel" -Method Post `
    -ContentType "application/json" -Body '{}'
```

To download a completed artifact through the API:

```powershell
$artifact = $jobDetails.artifacts | Select-Object -First 1
if ($null -eq $artifact) { throw "No artifact is available yet." }
$artifactQuery = [uri]::EscapeDataString($artifact.path)
Invoke-WebRequest "$studioUrl/api/jobs/$($studioJob.id)/artifact?path=$artifactQuery" `
    -OutFile (Join-Path (Get-Location) $artifact.name)
```

The download endpoint permits files only inside that job's output directory.
Cancelled and failed jobs may leave partial outputs; those are not successful
results. Cancellation is terminal for that job—submit a new job to rerun it.

## Workflow reference

The `slide_ids` array is ordered. Use registered image IDs, not filesystem paths.

| Workflow | Image selection order | Main parameters | Intended output |
| --- | --- | --- | --- |
| `extract` | One source slide | `source_magnification`, `target_magnification`, `detection_magnification`, `min_area_fraction`, `detector` (`otsu` or `semantic`) | Tissue regions and manifests |
| `align` | Reference first, moving slide second | `method` (`orb` or `valis`), `target_magnification`, `source_magnification`, `moving_source_magnification` | Aligned pyramidal TIFF and physical-resolution sidecar |
| `stain` | Image to normalize first, color-reference image second | `algorithm` (`reinhard`, `macenko`, or `vahadane`) | Normalized PNG and fitted weights |
| `count` | One source slide | Magnifications, `patch_size`, `min_cell_area`, `tissue_threshold` | DAB-positive cell-count results |
| `compare` | Reference, comparison A, comparison B | `dpi` | Three-image comparison figure and detail crops |

Current boundaries:

- Studio extraction currently calls the ordinary tissue-region API; it does
  not yet expose the library's TMA/core controls.
- Stain normalization fits the selected reference in the job. It is intended
  for extracted patches or ordinary images under 25 megapixels, not streamed
  whole-slide normalization. Loading a user-selected weights archive is not yet
  a Studio form/API option.
- `compare` generates a three-image figure. It is separate from the planned
  interactive two-pane viewer and does not register its inputs automatically.
- Physical magnification values such as `20` mean **20× objective power**, not
  pyramid level 20. Do not infer source magnification from image dimensions.
- Zero detected tissue regions or zero positive cells can be valid outcomes.
  Review summaries and logs rather than assuming a nonzero count is required.

## Workspace and job history

The intended on-disk layout is:

```text
<workspace>/
  studio.sqlite              Registered folders, image records, job history
  demo-slides/               Optional generated demonstration images
  jobs/<job-id>/
    request.json             Recorded inputs and parameters
    run.log                  Processing output and traceback, when applicable
    result.json              Worker outcome
    outputs/                 Generated results, including summary.json
```

Job states are `queued`, `running`, `succeeded`, `failed`, and `cancelled`.
Jobs recorded as running when Studio restarts are marked failed with an
interruption message. Queued jobs remain queued and may run after restart.
Back up this workspace if you need to preserve job history and outputs.

The `--static-dir` launcher option accepts a directory containing a built static
interface with an `index.html`. Do not point it at frontend source files or a
server bundle. The current generated frontend build has not yet been adapted
and verified for this handoff.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `No module named rocqipath` | Activate the intended Python environment and install the repository with `python -m pip install -e .`. |
| `No module named fastapi` or `uvicorn` | Install both packages in the same environment that launches Studio. |
| Browser root returns `404`, but `/api/status` works | The built static interface is absent; the API can run independently. |
| Frontend shows placeholder content | The generated scaffold has not yet been replaced with the Studio interface. |
| Port is already in use | Start with another port, for example `--port 8766`, and update your URLs. |
| Request returns `403` | Use the server's localhost origin. Cross-origin browser requests and unregistered artifact paths are rejected. |
| Mutation returns `415` | Send `Content-Type: application/json`, including an empty `{}` body for demo/cancel examples. |
| Job submission returns `409` | Check `/api/status` for unavailable workflow dependencies. |
| Submission returns `422` | Check workflow name, number of selected images, allowed parameter names, and numeric ranges. |
| Job fails with missing magnification | Supply the actual source magnification for metadata-poor images. |
| Large ordinary image cannot be viewed | The Pillow fallback rejects images above 100 million pixels; use a supported pyramidal WSI. |
| Job says `failed` | Open its detailed response and inspect `error` and `log`; partial files do not prove success. |

## Planned browser journey

Once UI integration is complete, the intended flow is: **add a folder → select
a slide → inspect or compare → choose a workflow → configure → run → review
logs and download results**. These controls are part of the approved design,
not yet a verified feature of the current scaffold.

See the [design](../docs/superpowers/specs/2026-09-07-studio-design.md) and
[implementation plan](../docs/superpowers/plans/2026-09-07-studio.md) for the
remaining work.
