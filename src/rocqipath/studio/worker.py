"""Execute a single Studio job in an isolated Python process."""

import json
from pathlib import Path
import sys
import traceback

from .workflows import execute


def main():
    """Record a truthful process result and preserve tracebacks in the log."""
    directory = Path(sys.argv[1])
    result = {}
    try:
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        execute(request["workflow"], request["inputs"], request["parameters"], directory / "outputs")
    except Exception as exc:
        traceback.print_exc()
        result["error"] = str(exc) or type(exc).__name__
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 1 if result else 0


if __name__ == "__main__":
    sys.exit(main())
