"""Launch RocqiPath Studio on localhost."""

import argparse
from pathlib import Path


def main():
    """Start the local browser workspace."""
    parser = argparse.ArgumentParser(description="RocqiPath Studio — local pathology workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, default=Path.home() / "RocqiPathStudio")
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    try:
        import uvicorn
        from .server import create_app
    except ImportError as exc:
        parser.exit(1, f"Studio dependencies are missing: {exc}. Install rocqipath[studio].\n")
    print(f"RocqiPath Studio: http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(args.workspace, args.static_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
