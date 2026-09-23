"""Launch RocqiPath Studio on localhost (also ``rocqipath studio``)."""

import argparse
from pathlib import Path


def serve(port: int = 8765, workspace: Path = Path.home() / "RocqiPathStudio", static_dir=None) -> int:
    """Start the local browser workspace and block until it stops.

    Parameters
    ----------
    port : int
        Loopback port to listen on.
    workspace : pathlib.Path
        Folder for Studio's database and job outputs.
    static_dir : pathlib.Path, optional
        Built interface to serve instead of the packaged one.

    Returns
    -------
    int
        Process exit status.
    """
    try:
        import uvicorn

        from .server import create_app
    except ImportError as exc:
        print(f"Studio dependencies are missing: {exc}. Install rocqipath[studio].")
        return 1
    print(f"RocqiPath Studio: http://127.0.0.1:{port}")
    uvicorn.run(create_app(workspace, static_dir), host="127.0.0.1", port=port)
    return 0


def main() -> int:
    """Parse Studio options and start the server."""
    parser = argparse.ArgumentParser(description="RocqiPath Studio — local pathology workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, default=Path.home() / "RocqiPathStudio")
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    return serve(args.port, args.workspace, args.static_dir)


if __name__ == "__main__":
    raise SystemExit(main())
