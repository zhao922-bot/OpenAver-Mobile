import threading
import time

from core import thumbnail_cache


class _ImageTracker:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def leave(self):
        with self.lock:
            self.active -= 1


class _FakeImage:
    width = 800
    height = 600

    def __init__(self, tracker):
        self._tracker = tracker

    def __enter__(self):
        self._tracker.enter()
        time.sleep(0.03)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._tracker.leave()
        return False

    def convert(self, _mode):
        return self

    def resize(self, _size, _resampling):
        return self

    def save(self, handle, *_args, **_kwargs):
        handle.write(b"webp")


def test_generate_limits_parallel_image_work(tmp_path, monkeypatch):
    tracker = _ImageTracker()
    monkeypatch.setattr(thumbnail_cache, "_generate_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(thumbnail_cache.Image, "open", lambda _path: _FakeImage(tracker))

    destinations = [tmp_path / "one.webp", tmp_path / "two.webp"]
    results = []

    def run(dst):
        results.append(thumbnail_cache.generate("cover.jpg", dst))

    threads = [threading.Thread(target=run, args=(dst,)) for dst in destinations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [True, True]
    assert tracker.max_active == 1


def test_generate_reuses_a_thumb_created_by_another_request(tmp_path, monkeypatch):
    dst = tmp_path / "cached.webp"
    dst.write_bytes(b"cached")

    def fail_open(_path):
        raise AssertionError("cached thumbnail should not reopen the source cover")

    monkeypatch.setattr(thumbnail_cache.Image, "open", fail_open)

    assert thumbnail_cache.generate("cover.jpg", dst) is True
