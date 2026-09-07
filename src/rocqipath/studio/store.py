"""Small persistent catalog and single-process job queue."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone


def now():
    """Return an ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Persist records and execute one isolated RocqiPath job at a time."""

    def __init__(self, root: Path):
        """Initialize the local database."""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "studio.sqlite"
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.process = None
        self.active_id = None
        self.thread = None
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, data TEXT)")
        for job in self.list("job"):
            if job["status"] == "running":
                job.update(status="failed", error="Studio stopped before this job completed.", finished=now())
                self.save("job", job)

    def connect(self):
        """Open a short-lived database connection."""
        return sqlite3.connect(self.db, timeout=20)

    def save(self, kind, record):
        """Insert or replace a catalog record."""
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?)", (kind, record["id"], json.dumps(record)))
        return record

    def list(self, kind):
        """Read records in insertion order."""
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, record_id):
        """Read one typed record."""
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return json.loads(row[0])

    def submit(self, workflow, inputs, parameters):
        """Persist a queued job before returning its identifier."""
        job_id = uuid.uuid4().hex
        directory = self.root / "jobs" / job_id
        directory.mkdir(parents=True)
        payload = {"workflow": workflow, "inputs": inputs, "parameters": parameters}
        (directory / "request.json").write_text(json.dumps(payload), encoding="utf-8")
        return self.save("job", {
            "id": job_id, "workflow": workflow, "status": "queued", "created": now(),
            "started": None, "finished": None, "error": None, "parameters": parameters,
            "inputs": [Path(p).name for p in inputs], "output_dir": str(directory / "outputs"),
        })

    def start(self):
        """Start the sequential worker monitor."""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        """Monitor subprocesses without blocking the API server."""
        while not self.stop.wait(0.2):
            with self.lock:
                queued = next((j for j in self.list("job") if j["status"] == "queued"), None)
                if queued is None:
                    continue
                job_id = queued["id"]
                directory = self.root / "jobs" / job_id
                queued.update(status="running", started=now())
                self.save("job", queued)
                self.active_id = job_id
                try:
                    log = (directory / "run.log").open("w", encoding="utf-8")
                    env = {**os.environ, "PYTHONUNBUFFERED": "1", "MPLBACKEND": "Agg"}
                    self.process = subprocess.Popen(
                        [sys.executable, "-m", "rocqipath.studio.worker", str(directory)],
                        stdout=log, stderr=subprocess.STDOUT, env=env,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception as exc:
                    queued.update(status="failed", error=str(exc), finished=now())
                    self.save("job", queued)
                    self.active_id = None
                    continue
            self.process.wait()
            log.close()
            with self.lock:
                job = self.get("job", job_id)
                if job["status"] == "running":
                    result_path = directory / "result.json"
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        result = {"error": "Processing stopped unexpectedly. See the job log."}
                    success = self.process.returncode == 0 and not result.get("error")
                    job.update(status="succeeded" if success else "failed", error=result.get("error"), finished=now())
                    self.save("job", job)
                self.process = None
                self.active_id = None

    def cancel(self, job_id):
        """Cancel queued work or terminate the active child process."""
        with self.lock:
            job = self.get("job", job_id)
            if job["status"] in {"queued", "running"}:
                job.update(status="cancelled", finished=now())
                self.save("job", job)
                if self.active_id == job_id and self.process is not None:
                    self.process.terminate()
            return job

    def close(self):
        """Stop accepting work and release the running process."""
        self.stop.set()
        with self.lock:
            if self.process is not None:
                self.process.terminate()
        if self.thread:
            self.thread.join(timeout=10)
