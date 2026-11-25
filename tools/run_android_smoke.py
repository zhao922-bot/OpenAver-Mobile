#!/usr/bin/env python3
"""Prepare and run smoke tests for a clean Android API 35 emulator."""

import argparse
import subprocess
from pathlib import Path


PACKAGE = "dev.openaver.mobile.debug"
RUNNER = f"{PACKAGE}.test/dev.openaver.mobile.smoke.EmulatorSmoke"


def generate_media(args):
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=240x160:rate=15",
        "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=44100",
        "-t", "120", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
        "-g", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-af", "volume=0.01", str(args.output),
    ], check=True, timeout=90)


def run_tests(args, parser):
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
        command("install", str(args.apk), check=True, timeout=120)
        command("install", str(args.test_apk), check=True, timeout=120)

        # Each am instrument invocation starts a fresh target process. The cold case
        # retains the first run's storage grant, so its first activity can bootstrap.
        for filename, options, marker, timeout in (
            ("instrumentation.txt", (), "OpenAver emulator smoke passed", 420),
            ("cold-notification.txt", ("-e", "scenario", "cold-notification"),
             "Cold notification opened Task Center", 150),
        ):
            report_path = args.artifacts / filename
            with report_path.open("w", encoding="utf-8") as output:
                result = command("shell", "am", "instrument", "-w", "-r", *options, RUNNER,
                                 stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            report = report_path.read_text(encoding="utf-8")
            print(report, end="")
            if (result.returncode != 0 or marker not in report
                    or "INSTRUMENTATION_CODE: -1" not in report):
                raise RuntimeError(f"OpenAver emulator smoke failed ({filename})")
    except Exception:
        for filename, adb_args in (
            ("screen.png", ("exec-out", "screencap", "-p")),
            ("logcat.txt", ("logcat", "-d", "-t", "700")),
            ("flutter-logcat.txt", ("logcat", "-d", "-s", "flutter:V", "AndroidRuntime:E")),
        ):
            try:
                with (args.artifacts / filename).open("wb") as output:
                    command(*adb_args, stdout=output, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate = subcommands.add_parser("generate-media", help="Generate the instrumentation asset")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--ffmpeg", default="ffmpeg")

    run = subcommands.add_parser("run", help="Install and run the app and test APKs")
    run.add_argument("--apk", type=Path, required=True)
    run.add_argument("--test-apk", type=Path, required=True)
    run.add_argument("--adb", default="adb")
    run.add_argument("--device", help="adb serial of a clean emulator")
    run.add_argument("--artifacts", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "generate-media":
        generate_media(args)
    else:
        run_tests(args, run)


if __name__ == "__main__":
    main()
