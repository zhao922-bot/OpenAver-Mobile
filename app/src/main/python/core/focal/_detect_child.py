"""Focal detection child process entry point (CD-152b-1 / CD-152b-2).

Stdout channel is exactly two UTF-8 lines, each flushed:
  1. READY — after import, immediately before detect_focal
  2. JSON  — {"focal": [x, y]} or {"focal": null} at full float precision

Unexpected exceptions are swallowed (nothing extra on stdout); diagnostics
go to stderr so the parent can treat a missing result line as abandoned.
"""
from __future__ import annotations

import json
import sys
import traceback


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv if argv is None else argv
    try:
        fs_path = argv[1]
        ratio = float(argv[2])
        from core.focal.detector import detect_focal

        print("READY", flush=True)
        focal = detect_focal(fs_path, ratio)
        print(json.dumps({"focal": list(focal) if focal is not None else None}), flush=True)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
