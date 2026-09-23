"""Loopback-only local API and static interface hosting."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from rocqipath import __version__
from . import slides
from .store import Store
from . import catalog as workflow_catalog


class FolderRequest(BaseModel):
    """An explicitly selected local folder."""

    path: str


class InputRef(BaseModel):
    """A registered slide or folder, or a previous job's outputs."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["slide", "folder", "job"]
    id: str = Field(min_length=1, max_length=64)


class JobRequest(BaseModel):
    """A workflow, its inputs, and settings validated against its config."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    workflow: str = Field(min_length=1, max_length=64)
    inputs: list[InputRef] = Field(min_length=1, max_length=50)
    options: dict[str, InputRef] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


def create_app(workspace: Path, static_dir: Path | None = None):
    """Create the local application without starting it during import."""
    store = Store(Path(workspace))

    @asynccontextmanager
    async def lifespan(_app):
        store.start()
        yield
        store.close()

    app = FastAPI(title="RocqiPath Studio", lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "Studio accepts localhost requests only."}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
                return JSONResponse({"detail": "Cross-origin requests are not permitted."}, status_code=403)
        if request.method in {"POST", "PUT", "DELETE"} and request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"detail": "Use application/json for local actions."}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(KeyError)
    async def missing(_request, _exc):
        return JSONResponse({"detail": "The requested item is not registered."}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(_request, _exc):
        return JSONResponse({"detail": "The file or folder no longer exists."}, status_code=404)

    @app.exception_handler(PermissionError)
    async def denied(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/status")
    def status():
        return {"version": __version__, "workspace": str(store.root)}

    @app.get("/api/workflows")
    def workflows():
        return workflow_catalog.catalog()

    @app.get("/api/browse")
    def browse(path: str | None = None):
        root = Path(path).expanduser().resolve(strict=True) if path else Path.home()
        if not root.is_dir():
            raise ValueError("Choose a directory.")
        directories = []
        for entry in root.iterdir():
            try:
                if entry.is_dir() and not entry.name.startswith("."):
                    directories.append({"name": entry.name, "path": str(entry)})
            except OSError:
                continue
        return {"path": str(root), "parent": str(root.parent), "directories": sorted(directories, key=lambda x: x["name"].lower())[:500]}

    @app.get("/api/folders")
    def folders():
        return store.list("folder")

    @app.post("/api/folders")
    def import_folder(body: FolderRequest):
        return slides.scan(store, body.path)

    @app.post("/api/demo")
    def demo():
        return slides.create_demo(store)

    @app.get("/api/slides")
    def catalog():
        return store.list("slide")

    @app.get("/api/slides/{slide_id}/info")
    def metadata(slide_id: str):
        return slides.info(slides.resolve_slide(store, slide_id))

    @app.get("/api/slides/{slide_id}/thumbnail")
    def thumbnail(slide_id: str):
        return Response(slides.jpeg(slides.resolve_slide(store, slide_id)), media_type="image/jpeg")

    @app.get("/api/slides/{slide_id}/tiles/{level}/{x}/{y}.jpg")
    def tile(slide_id: str, level: int, x: int, y: int):
        return Response(slides.jpeg(slides.resolve_slide(store, slide_id), level, x, y), media_type="image/jpeg")

    @app.get("/api/jobs")
    def jobs():
        return sorted(store.list("job"), key=lambda j: j["created"], reverse=True)

    def resolve(ref: InputRef) -> str:
        """Turn a browser reference into a contained local path."""
        if ref.kind == "slide":
            return str(slides.resolve_slide(store, ref.id))
        if ref.kind == "folder":
            return str(Path(store.get("folder", ref.id)["path"]).resolve(strict=True))
        job = store.get("job", ref.id)
        if job["status"] != "succeeded":
            raise ValueError("Only a succeeded job's outputs can be used as input.")
        return str(Path(job["output_dir"]).resolve(strict=True))

    @app.post("/api/jobs")
    def submit(body: JobRequest):
        try:
            workflow = workflow_catalog.validate(body.workflow, body.settings, list(body.options))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        inputs = [resolve(ref) for ref in body.inputs]
        options = {name: resolve(ref) for name, ref in body.options.items()}
        return store.submit(workflow.name, inputs, {"options": options, "settings": body.settings})

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str):
        job = store.get("job", job_id)
        root = Path(job["output_dir"])
        artifacts = []
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.resolve().is_relative_to(root.resolve()):
                    artifacts.append({"name": path.name, "path": path.relative_to(root).as_posix(), "size": path.stat().st_size})
                    if len(artifacts) >= 500:
                        break
        log_path = root.parent / "run.log"
        if log_path.exists():
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size - 40000))
                log = stream.read().decode("utf-8", errors="replace")
        else:
            log = "Waiting for the local worker…"
        return {**job, "artifacts": artifacts, "log": log}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return store.cancel(job_id)

    @app.get("/api/jobs/{job_id}/artifact")
    def artifact(job_id: str, path: str):
        job = store.get("job", job_id)
        root = Path(job["output_dir"]).resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise PermissionError("Artifact path is outside this job.")
        if not target.is_file():
            raise FileNotFoundError(target)
        return FileResponse(target, filename=target.name)

    static_dir = static_dir or Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="interface")
    return app
