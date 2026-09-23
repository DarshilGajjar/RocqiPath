"""Execute a single Studio job in an isolated Python process."""

import json
import sys
import traceback
from pathlib import Path


def main():
    """Run the requested workflow and record a truthful result."""
    directory = Path(sys.argv[1])
    result = {}
    try:
        from rocqipath.registry import get_workflow
        from rocqipath.studio.catalog import build_config

        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        workflow = get_workflow(request["workflow"])
        print(f"Starting {workflow.name}", flush=True)
        for path in request["inputs"]:
            print(f"Input: {path}", flush=True)
        inputs = request["inputs"][0] if len(request["inputs"]) == 1 else request["inputs"]
        outcome = workflow.function(
            inputs,
            directory / "outputs",
            config=build_config(workflow, request.get("settings", {})),
            **request.get("options", {}),
        )
        summary = {"items": len(outcome), "summary": outcome.summary}
        (directory / "outputs" / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        print(f"Processing completed: {len(outcome)} file(s) produced.", flush=True)
    except Exception as exc:
        traceback.print_exc()
        result["error"] = str(exc) or type(exc).__name__
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 1 if result else 0


if __name__ == "__main__":
    sys.exit(main())
