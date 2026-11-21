#!/usr/bin/env python3
"""Install and test the debug APK on a clean Android API 35 emulator."""

import argparse
import subprocess
import tempfile
from pathlib import Path


PACKAGE = "dev.openaver.mobile.debug"
RUNNER = f"{PACKAGE}.test/dev.openaver.mobile.smoke.EmulatorSmoke"
LIBRARY = "/sdcard/Movies/OpenAverSmoke"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--test-apk", type=Path, required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--device", help="adb serial of a clean emulator")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()

    adb = [args.adb]
    if args.device:
        adb.extend(["-s", args.device])

    def command(*options, **kwargs):
        return subprocess.run([*adb, *options], timeout=kwargs.pop("timeout", 45), **kwargs)

    for apk in (args.apk, args.test_apk):
        if not apk.is_file():
            parser.error(f"APK does not exist: {apk}")
    serial = command("get-serialno", capture_output=True, text=True, check=True).stdout.strip()
    if not serial.startswith("emulator-"):
        parser.error(f"An Android emulator is required, got {serial!r}")
    packages = command("shell", "pm", "list", "packages", PACKAGE,
                       capture_output=True, text=True, check=True).stdout.splitlines()
    if f"package:{PACKAGE}" in packages:
        parser.error("The emulator already has OpenAver debug installed; use a clean emulator.")

    args.artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="openaver-smoke-") as tmp:
            clip = Path(tmp) / "smoke.mp4"
            subprocess.run([
                args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=240x160:rate=15",
                "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=44100",
                "-t", "120", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
                "-g", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-af", "volume=0.01", str(clip),
            ], check=True, timeout=90)
            command("shell", "mkdir", "-p", LIBRARY, check=True)
            for part in (1, 2):
                command("push", str(clip), f"{LIBRARY}/TST-12400-CD{part}.mp4", check=True)
        command("install", str(args.apk), check=True, timeout=120)
        command("install", str(args.test_apk), check=True, timeout=120)

        with (args.artifacts / "instrumentation.txt").open("w", encoding="utf-8") as output:
            result = command("shell", "am", "instrument", "-w", "-r", RUNNER,
                             stdout=output, stderr=subprocess.STDOUT, timeout=420)
        report = (args.artifacts / "instrumentation.txt").read_text(encoding="utf-8")
        print(report, end="")
        if (result.returncode != 0 or "OpenAver emulator smoke passed" not in report
                or "INSTRUMENTATION_CODE: -1" not in report):
            raise RuntimeError("OpenAver emulator smoke failed")
    except Exception:
        for filename, adb_args in (
            ("screen.png", ("exec-out", "screencap", "-p")),
            ("logcat.txt", ("logcat", "-d", "-t", "700")),
        ):
            try:
                with (args.artifacts / filename).open("wb") as output:
                    command(*adb_args, stdout=output, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        raise


if __name__ == "__main__":
    main()
