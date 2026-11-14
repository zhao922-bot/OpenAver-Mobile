"""Check the built Python archive without reading configuration contents."""
from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path, PurePosixPath


def verify_payload(archive: zipfile.ZipFile) -> int:
    names = set(archive.namelist())
    runtime_files = []
    for name in names:
        path = PurePosixPath(name)
        if path.parts and (
            path.parts[0] in {"output", "logs"}
            or path.as_posix() == "web/config.json"
        ):
            runtime_files.append(name)
    if runtime_files:
        raise ValueError("Runtime files bundled in Python payload: " + ", ".join(sorted(runtime_files)))
    required = {"web/config.default.json", "web/templates/settings.html"}
    missing = required - names
    if not ({"openaver_boot.py", "openaver_boot.pyc"} & names):
        missing.add("openaver_boot.py[c]")
    if missing:
        raise ValueError("Missing application files: " + ", ".join(sorted(missing)))
    return len(names)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path, help="app.imy or APK to verify")
    args = parser.parse_args()
    try:
        with zipfile.ZipFile(args.archive) as outer:
            if "assets/chaquopy/app.imy" in outer.namelist():
                with zipfile.ZipFile(io.BytesIO(outer.read("assets/chaquopy/app.imy"))) as payload:
                    count = verify_payload(payload)
            else:
                count = verify_payload(outer)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(f"Python payload verified: {count} entries, no bundled runtime data")


if __name__ == "__main__":
    main()
