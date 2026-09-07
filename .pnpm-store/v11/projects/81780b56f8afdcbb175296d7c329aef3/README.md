# RocqiPath Studio web interface

**Status: unfinished interface scaffold.** The Python Studio API has been
written but is not yet verified, and this frontend is not connected to it.

Read the [local Studio usage guide](../how_to_use/09_Studio_Web.md) for Python
setup, backend launch, frontend development, API examples, workflow inputs,
output locations, and troubleshooting.

Install frontend dependencies once, from this directory:

```console
pnpm install
```

Then start the frontend from the repository root using **Git Bash** on Windows,
or Bash on macOS/Linux:

```bash
bash start-studio.sh
```

The script locates `studio-web` relative to itself, so an absolute path to the
script also works from another directory. It finds pnpm, installs missing
frontend dependencies, then runs `pnpm dev` in the foreground;
press **Ctrl+C** to stop. Extra arguments are forwarded, for example
`bash start-studio.sh --port 3001`. Node.js and pnpm must be on your shell's PATH.

Open the local address printed by the development server. Starting this
preview does not start the RocqiPath backend. The generated `pnpm start`
script uses Wrangler; it is not the final local Studio launcher.

The backend entry point, from the repository root in a prepared Python
3.10–3.11 environment, is:

```console
python -m rocqipath.studio --port 8765
```

Its [status endpoint](http://127.0.0.1:8765/api/status) and
[API reference](http://127.0.0.1:8765/docs) are independent of the frontend.
See the full guide before submitting processing jobs.
