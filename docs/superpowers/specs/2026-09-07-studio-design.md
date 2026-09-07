# RocqiPath Studio

Approved scope: local browser workspace, slide library, zoomable side-by-side
viewer, five RocqiPath workflows, background jobs with logs and saved outputs.

The React interface lives in `studio-web`; a FastAPI service in
`src/rocqipath/studio` serves the built interface and API on loopback. Python
3.10–3.11 remains supported. No cloud service, upload, or user account is needed.
Folders are selected through a local directory browser. Registered folders and
job history persist in SQLite in a user-selected Studio workspace. Images are
referenced in place. Output files are isolated per job in that workspace.

The viewer serves bounded image tiles using OpenSlide for supported WSIs and
Pillow for ordinary images. A synthetic demonstration collection is explicitly
labelled and opt-in. The image viewer has pan, zoom, reset and a comparison pane.
Metadata reports known values and identifies unknown magnification.

Workflow forms map to typed RocqiPath configuration, with required parameters
and installed backend availability visible. One child process executes a job
at a time; the UI stays responsive. Jobs persist queued/running/succeeded/failed/
cancelled states, log output and artifact paths. Interrupted jobs are marked
failed on restart. No invented percentage progress. Cancellation terminates the
job process. Results can be downloaded from paths restricted to that job.

Only loopback hosts are accepted. Mutations require same-origin JSON requests.
File endpoints accept registered slide IDs, never unrestricted download paths.
Browse/import is an explicit local action. Errors remain actionable and visible.

Visual direction: warm white, charcoal navigation, plum accents, editorial
headings, compact controls, prominent slide imagery. Responsive sidebar,
keyboard-accessible forms, loading/empty/error states. No fake patient records.

Verification: backend tests for path containment, jobs, errors and real library
dispatch; frontend production build; existing suite; HTTP checks and local preview.
Full scanner/model validation depends on locally available data and backends.
