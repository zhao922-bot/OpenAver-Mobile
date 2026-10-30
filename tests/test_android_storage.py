from __future__ import annotations

import errno

import pytest

from core import android_storage


class FakeBridge:
    def __init__(self, write_error=None):
        self.write_error = write_error
        self.writes = []

    def hasAccessForPath(self, _path):
        return True

    def writeBytes(self, path, data, create_parents):
        self.writes.append((path, data, create_parents))
        return self.write_error


def test_android_storage_writes_bytes_through_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(android_storage, "_bridge", lambda: bridge)

    android_storage.write_bytes("/storage/SD/JAV/ABC.nfo", b"xml")

    assert bridge.writes == [
        ("/storage/SD/JAV/ABC.nfo", b"xml", True)
    ]


def test_android_storage_reports_bridge_failure(monkeypatch):
    bridge = FakeBridge(write_error="verify_failed")
    monkeypatch.setattr(android_storage, "_bridge", lambda: bridge)

    with pytest.raises(android_storage.AndroidStorageWriteError, match="verify_failed"):
        android_storage.write_bytes("/storage/SD/JAV/ABC.nfo", b"xml")


def test_android_storage_requires_path_specific_access(monkeypatch):
    class DeniedBridge:
        def hasAccessForPath(self, _path):
            return False

    monkeypatch.setattr(android_storage, "_bridge", lambda: DeniedBridge())

    with pytest.raises(android_storage.AndroidStoragePermissionError):
        android_storage.write_bytes("/storage/SD/JAV/ABC.nfo", b"xml")


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("denied"),
        OSError(errno.EROFS, "read-only filesystem"),
        OSError(errno.EACCES, "denied"),
    ],
)
def test_android_storage_recognizes_access_errors(error):
    assert android_storage.is_access_error(error)


def test_android_storage_does_not_treat_disk_full_as_access_error():
    assert not android_storage.is_access_error(
        OSError(errno.ENOSPC, "no space left")
    )
